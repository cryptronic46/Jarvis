from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from time import monotonic, time
from typing import Any
import json

from jarvis_core.services.secret_store import get_secret, secret_status
from jarvis_core.services.user_memory import store as user_memory_store
from jarvis_core.services.privacy import privacy_state
from jarvis_core.services.context_store import context_store


CLOUD_SYSTEM_PROMPT = """
You are the cloud reasoning layer of JARVIS, a hybrid assistant running on a
Windows PC.

Cybersecurity role:
- You may act as a cybersecurity teacher for the user's own/authorized systems and labs.
- Teach concepts with defensive context, evidence standards and safe verification.
- Distinguish facts, inference and unknowns; do not call normal network activity an intrusion.
- Local security telemetry remains authoritative and should stay local unless exposed through an allowed compact tool.
- The Cyber Knowledge Vault is local by default. Do not assume its documents are available in cloud unless an explicit safe retrieval tool is allowlisted.
- Never imply that a third-party target is authorized unless the user explicitly says so.

Rules:
- Speak European Portuguese (pt-PT) by default.
- Be concise and natural because the response may be spoken aloud.
- The local computer remains the authority for actions and telemetry.
- The Senhor is the absolute final authority for autonomous external actions. The cloud model cannot approve, widen, bypass or invent an owner authorization.
- A direct user order authorizes only its exact requested scope. Never infer a standing permission.
- Autonomy authorization is enforced locally before this cloud layer is called; never claim you granted yourself permission.
- If this cloud layer is called for owner-authorized external learning, perform the exact requested research scope instead of asking for authorization again.
- Do not append decorative emoji unless the user explicitly asks for emoji.
- Never invent a local action. Use an exposed function tool if an action is needed.
- Never ask for or expose API keys, passwords, tokens, private keys or secrets.
- Never request arbitrary shell, PowerShell, cmd, registry modification, file
  deletion or privileged execution. Those capabilities are intentionally absent.
- A close_application call may require explicit user confirmation. If the tool
  output contains confirmation_required, tell the user the exact /confirm TOKEN.
- If web search is available and the question needs current public information,
  use it.
- Address the user as Senhor; his name is Tiago.
- Prefer local get_home_environment for home weather/marine conditions.
- Prefer get_precise_location for location; never use IP geolocation.
- Do not expose private chain-of-thought. Give conclusions and relevant checks only.
""".strip()

EXPERT_SYSTEM_PROMPT = """
You are an external expert consulted by a local assistant for one difficult question.
Return a concise, technically useful answer in European Portuguese.
Treat the supplied question as the complete context. Do not ask for passwords, API
keys, tokens, private keys, personal files, telemetry or hidden chain-of-thought.
Do not assume access to the user's device, memory, identity or prior conversation.
Distinguish facts, uncertainty and assumptions. Do not claim that any local action was
performed.
""".strip()


@dataclass(slots=True)
class CloudAnswer:
    ok: bool
    text: str
    model: str | None = None
    elapsed_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: float = 0.0
    used_web: bool = False
    tool_calls: int = 0
    error: str | None = None
    provider_error_code: str | None = None
    retryable: bool | None = None


class CloudBrain:
    """
    OpenAI Responses API adapter.

    The legacy ask() path retains compact cloud-history/tool compatibility. The
    0.27.8 consult() expert path is strictly one-shot: exact authorized question
    only, no local tools/profile/history, and store=False. Raw microphone audio is
    never sent here.
    """

    DEFAULT_ALLOWED_TOOLS = {
        "get_current_time",
        "get_precise_location",
        "get_configured_location",
        "get_home_environment",
        "get_user_profile",
        "recall_user_memory",
        "get_system_status",
        "get_pre_request_telemetry",
        "get_recent_telemetry",
        "list_available_apps",
        "inspect_application",
        "open_application",
        "close_application",
        "get_master_volume",
        "set_master_volume",
        "set_mute",
    }

    MODEL_PRICES = {
        # USD per 1M tokens; estimate only, updated for the 0.6.0 release.
        "gpt-5.6-terra": (2.0, 12.0),
        "gpt-5.6-sol": (4.0, 20.0),
        "gpt-5.6": (4.0, 20.0),
        "gpt-5.6-luna": (0.20, 1.20),
    }

    def __init__(self, settings, events, tools):
        self.settings = settings
        self.events = events
        self.tools = tools
        self._client = None
        self._lock = RLock()
        self._history: list[dict[str, str]] = []
        self._session_input_tokens = 0
        self._session_output_tokens = 0
        self._session_estimated_usd = 0.0
        self._session_requests = 0

    def _api_key(self) -> str | None:
        return get_secret("openai_api_key", "OPENAI_API_KEY")


    def credential_status(self) -> dict[str, Any]:
        status = secret_status(
            "openai_api_key",
            "OPENAI_API_KEY",
        )
        return {
            **status,
            "privacy_mode": bool(
                privacy_state().enabled
            ),
            "cloud_enabled": bool(
                self.settings.cloud_enabled
            ),
        }


    @staticmethod
    def _safe_provider_error(exc: Exception) -> tuple[str | None, str | None]:
        """Return provider error code/type without exposing secrets or raw payloads."""
        body = getattr(exc, "body", None)
        if not isinstance(body, dict):
            return None, None
        payload = body.get("error", body)
        if not isinstance(payload, dict):
            return None, None
        code = payload.get("code")
        error_type = payload.get("type")
        return (
            str(code)[:120] if code else None,
            str(error_type)[:120] if error_type else None,
        )

    @classmethod
    def _classify_cloud_error(
        cls,
        exc: Exception,
    ) -> tuple[str, str, str | None, bool | None]:
        exc_name = type(exc).__name__
        raw_message = str(exc or "")
        lowered = raw_message.lower()
        provider_code, provider_type = cls._safe_provider_error(exc)
        provider_lower = str(provider_code or "").lower()
        type_lower = str(provider_type or "").lower()

        if (
            exc_name == "AuthenticationError"
            or "invalid_api_key" in lowered
            or "incorrect api key" in lowered
        ):
            return (
                "OPENAI_AUTH_INVALID",
                "A OpenAI rejeitou a credencial configurada. "
                "A pesquisa cloud não foi executada. "
                "Usa /cloud diagnose e volta a configurar a chave "
                "sem a partilhar no terminal/chat.",
                provider_code,
                False,
            )

        quota_codes = {
            "credit_balance_exhausted",
            "organization_usage_limit_exceeded",
            "organization_spend_limit_exceeded",
            "project_spend_limit_exceeded",
            "insufficient_quota",
        }
        if (
            exc_name == "RateLimitError"
            and (provider_lower in quota_codes or type_lower == "insufficient_quota")
        ):
            return (
                "OPENAI_QUOTA_OR_BILLING",
                "A OpenAI recusou o pedido por quota, saldo ou limite de despesas. "
                "A aprendizagem não foi executada. Usa /cloud diagnose para ver "
                "o código seguro e corrige primeiro a faturação/limite aplicável.",
                provider_code or provider_type,
                False,
            )

        if exc_name == "RateLimitError":
            return (
                "OPENAI_RATE_LIMIT_TEMPORARY",
                "A OpenAI aplicou um limite temporário de pedidos/tokens. "
                "A aprendizagem não foi executada. Não repitas continuamente; "
                "usa /cloud diagnose e tenta novamente depois do limite aliviar.",
                provider_code,
                True,
            )

        return (
            exc_name,
            f"Falha na camada cloud: {exc_name}. "
            "Usa /cloud diagnose para diagnóstico seguro.",
            provider_code,
            None,
        )

    def reset_client(self) -> None:
        with self._lock:
            self._client = None
        self.events.emit("CLOUD_CLIENT_RESET")

    def available(self) -> bool:
        if not bool(getattr(self.settings, "external_ai_enabled", False)):
            return False
        if privacy_state().enabled:
            return False
        if not self.settings.cloud_enabled:
            return False
        if not self._api_key():
            return False
        try:
            import openai  # noqa: F401
            return True
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        try:
            import openai  # noqa: F401
            package = True
        except Exception:
            package = False

        credential = self.credential_status()
        return {
            "enabled": self.settings.cloud_enabled,
            "configured": bool(
                credential.get("configured")
            ),
            "credential_source": credential.get(
                "effective_source"
            ),
            "environment_override": bool(
                credential.get(
                    "environment_overrides_credential_manager"
                )
            ),
            "sdk_installed": package,
            "available": self.available(),
            "mode": self.settings.hybrid_mode,
            "model": self.settings.cloud_model,
            "deep_model": self.settings.cloud_model_deep,
            "web_search": self.settings.cloud_web_search,
            "store": False,
            "audio_sent_to_cloud": False,
            "session_requests": self._session_requests,
            "session_input_tokens": self._session_input_tokens,
            "session_output_tokens": self._session_output_tokens,
            "session_estimated_usd": round(self._session_estimated_usd, 6),
        }


    def diagnose(self) -> dict[str, Any]:
        """Explicit safe cloud diagnostic; never returns any API-key material."""
        credential = self.credential_status()

        try:
            import openai  # noqa: F401
            sdk_installed = True
        except Exception:
            sdk_installed = False

        result = {
            "ok": True,
            "credential": credential,
            "sdk_installed": sdk_installed,
            "configured_model": self.settings.cloud_model,
            "privacy_mode": bool(
                privacy_state().enabled
            ),
            "connection_tested": False,
            "connection_ok": False,
            "connection_message": None,
            "error": None,
            "provider_error_code": None,
            "retryable": None,
        }

        if (
            not credential.get("configured")
            or not sdk_installed
            or privacy_state().enabled
            or not self.settings.cloud_enabled
            or not bool(getattr(self.settings, "external_ai_enabled", False))
        ):
            return result

        tested = self.test()
        result["connection_tested"] = True
        result["connection_ok"] = bool(
            tested.ok
        )
        result["connection_message"] = tested.text
        result["error"] = tested.error
        result["provider_error_code"] = tested.provider_error_code
        result["retryable"] = tested.retryable
        return result

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
        self.events.emit("CLOUD_CONTEXT_CLEARED")

    def _client_or_raise(self):
        if not bool(getattr(self.settings, "external_ai_enabled", False)):
            raise RuntimeError("EXTERNAL_AI_DISABLED")
        if self._client is not None:
            return self._client

        key = self._api_key()
        if not key:
            raise RuntimeError(
                "OpenAI API não configurada. Executa .\\setup_cloud.ps1."
            )

        from openai import OpenAI
        self._client = OpenAI(api_key=key)
        return self._client

    def _api_function_tools(self) -> list[dict[str, Any]]:
        allowed = set(self.settings.cloud_tool_allowlist or self.DEFAULT_ALLOWED_TOOLS)
        result = []
        for schema in self.tools.schemas:
            fn = schema.get("function", {})
            name = fn.get("name")
            if name not in allowed:
                continue
            result.append({
                "type": "function",
                "name": name,
                "description": fn.get("description", ""),
                "parameters": fn.get(
                    "parameters",
                    {"type": "object", "properties": {}},
                ),
            })
        return result

    @staticmethod
    def _item_dump(item) -> dict[str, Any]:
        if hasattr(item, "model_dump"):
            return item.model_dump()
        if isinstance(item, dict):
            return item
        raise TypeError(f"Unsupported Responses output item: {type(item).__name__}")

    @staticmethod
    def _usage(response) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0

        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens", input_tokens) or 0
            output_tokens = usage.get("output_tokens", output_tokens) or 0

        return int(input_tokens), int(output_tokens)

    @classmethod
    def _estimate_cost(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = cls.MODEL_PRICES.get(model)
        if not prices:
            return 0.0
        in_price, out_price = prices
        return (
            input_tokens / 1_000_000 * in_price
            + output_tokens / 1_000_000 * out_price
        )

    def _trim_history(self) -> None:
        limit = max(2, int(self.settings.cloud_history_turns)) * 2
        if len(self._history) > limit:
            self._history = self._history[-limit:]

    def test(self) -> CloudAnswer:
        return self.ask(
            "Responde apenas: CLOUD OK",
            use_web=False,
            deep=False,
            test_mode=True,
        )

    def consult(
        self,
        user_text: str,
        *,
        deep: bool = True,
    ) -> CloudAnswer:
        """One-shot privacy-preserving expert consultation.

        Only the exact authorized question and this neutral expert instruction are
        sent. JARVIS memory, profile, local telemetry, tool schemas and cloud
        conversation history are intentionally excluded.
        """
        started = monotonic()
        with self._lock:
            try:
                client = self._client_or_raise()
                model = (
                    self.settings.cloud_model_deep
                    if deep
                    else self.settings.cloud_model
                )
                reasoning_effort = (
                    self.settings.cloud_reasoning_deep
                    if deep
                    else self.settings.cloud_reasoning
                )
                self.events.emit(
                    "EXPERT_CLOUD_REQUEST",
                    model=model,
                    isolated=True,
                    tools=False,
                    history=False,
                    profile=False,
                )
                response = client.responses.create(
                    model=model,
                    instructions=EXPERT_SYSTEM_PROMPT,
                    input=[{"role": "user", "content": str(user_text or "")}],
                    reasoning={"effort": reasoning_effort},
                    text={"verbosity": self.settings.cloud_verbosity},
                    store=False,
                    max_output_tokens=int(self.settings.cloud_max_output_tokens),
                )
                input_tokens, output_tokens = self._usage(response)
                output_text = (getattr(response, "output_text", "") or "").strip()
                if not output_text:
                    output_text = "A consulta externa não devolveu uma resposta utilizável."
                elapsed_ms = round((monotonic() - started) * 1000)
                estimated = self._estimate_cost(model, input_tokens, output_tokens)
                self._session_requests += 1
                self._session_input_tokens += input_tokens
                self._session_output_tokens += output_tokens
                self._session_estimated_usd += estimated
                self.events.emit(
                    "EXPERT_CLOUD_RESPONSE",
                    model=model,
                    elapsed_ms=elapsed_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_usd=round(estimated, 6),
                    isolated=True,
                )
                return CloudAnswer(
                    ok=True,
                    text=output_text,
                    model=model,
                    elapsed_ms=elapsed_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_usd=estimated,
                    used_web=False,
                    tool_calls=0,
                )
            except Exception as exc:
                elapsed_ms = round((monotonic() - started) * 1000)
                error_code, safe_message, provider_error_code, retryable = (
                    self._classify_cloud_error(exc)
                )
                if error_code == "OPENAI_AUTH_INVALID":
                    self._client = None
                self.events.emit(
                    "EXPERT_CLOUD_ERROR",
                    error=error_code,
                    elapsed_ms=elapsed_ms,
                    isolated=True,
                )
                return CloudAnswer(
                    ok=False,
                    text=safe_message,
                    elapsed_ms=elapsed_ms,
                    error=error_code,
                    provider_error_code=provider_error_code,
                    retryable=retryable,
                )

    def ask(
        self,
        user_text: str,
        *,
        use_web: bool = False,
        deep: bool = False,
        test_mode: bool = False,
    ) -> CloudAnswer:
        started = monotonic()
        with self._lock:
            try:
                client = self._client_or_raise()
                model = (
                    self.settings.cloud_model_deep
                    if deep
                    else self.settings.cloud_model
                )
                reasoning_effort = (
                    self.settings.cloud_reasoning_deep
                    if deep
                    else self.settings.cloud_reasoning
                )

                history = [] if test_mode else list(self._history)
                input_items: list[Any] = [
                    *history,
                    {"role": "user", "content": user_text},
                ]

                api_tools = self._api_function_tools()
                if use_web and self.settings.cloud_web_search:
                    api_tools.append({"type": "web_search"})

                total_in = 0
                total_out = 0
                total_tool_calls = 0
                rounds = 0
                response = None

                self.tools.request_started_at = time()
                self.events.emit(
                    "CLOUD_REQUEST",
                    model=model,
                    web=bool(use_web and self.settings.cloud_web_search),
                    deep=deep,
                )

                while rounds < max(1, int(self.settings.cloud_max_tool_rounds)):
                    rounds += 1

                    kwargs = {
                        "model": model,
                        "instructions": (
                            CLOUD_SYSTEM_PROMPT
                            + "\nUser profile: "
                            + json.dumps(
                                user_memory_store().profile(),
                                ensure_ascii=False,
                            )
                            + (
                                "\n"
                                + context_store().prompt_block(
                                    int(getattr(self.settings, "persistent_context_turns", 4))
                                )
                                if getattr(self.settings, "persistent_context_enabled", True)
                                else ""
                            )
                        ),
                        "input": input_items,
                        "reasoning": {"effort": reasoning_effort},
                        "text": {"verbosity": self.settings.cloud_verbosity},
                        "store": False,
                        "max_output_tokens": int(self.settings.cloud_max_output_tokens),
                        "include": ["reasoning.encrypted_content"],
                    }
                    if api_tools:
                        kwargs["tools"] = api_tools
                        kwargs["tool_choice"] = "auto"

                    response = client.responses.create(**kwargs)

                    in_tok, out_tok = self._usage(response)
                    total_in += in_tok
                    total_out += out_tok

                    function_calls = [
                        item for item in (getattr(response, "output", None) or [])
                        if getattr(item, "type", None) == "function_call"
                    ]

                    if not function_calls:
                        break

                    outputs = []
                    for call in function_calls:
                        total_tool_calls += 1
                        name = getattr(call, "name", "")
                        raw_args = getattr(call, "arguments", "") or "{}"
                        try:
                            arguments = json.loads(raw_args)
                            if not isinstance(arguments, dict):
                                arguments = {}
                        except json.JSONDecodeError:
                            arguments = {}

                        if name not in set(
                            self.settings.cloud_tool_allowlist
                            or self.DEFAULT_ALLOWED_TOOLS
                        ):
                            result = json.dumps({
                                "error": "CLOUD_TOOL_NOT_ALLOWED",
                                "tool": name,
                            }, ensure_ascii=False)
                        else:
                            self.events.emit(
                                "CLOUD_LOCAL_TOOL_REQUEST",
                                tool=name,
                            )
                            result = self.tools.execute(name, arguments)

                        outputs.append({
                            "type": "function_call_output",
                            "call_id": getattr(call, "call_id", ""),
                            "output": result,
                        })

                    # Stateless continuation: include model output items plus local
                    # function results in the next request.
                    input_items.extend(
                        self._item_dump(item)
                        for item in (getattr(response, "output", None) or [])
                    )
                    input_items.extend(outputs)

                if response is None:
                    raise RuntimeError("A OpenAI não devolveu resposta.")

                output_text = (getattr(response, "output_text", "") or "").strip()
                if not output_text:
                    output_text = "Não obtive uma resposta cloud utilizável."

                elapsed_ms = round((monotonic() - started) * 1000)
                estimated = self._estimate_cost(model, total_in, total_out)

                self._session_requests += 1
                self._session_input_tokens += total_in
                self._session_output_tokens += total_out
                self._session_estimated_usd += estimated

                if not test_mode:
                    self._history.extend([
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": output_text},
                    ])
                    self._trim_history()

                self.events.emit(
                    "CLOUD_RESPONSE",
                    model=model,
                    elapsed_ms=elapsed_ms,
                    input_tokens=total_in,
                    output_tokens=total_out,
                    estimated_usd=round(estimated, 6),
                    web=bool(use_web and self.settings.cloud_web_search),
                    tool_calls=total_tool_calls,
                )
                return CloudAnswer(
                    ok=True,
                    text=output_text,
                    model=model,
                    elapsed_ms=elapsed_ms,
                    input_tokens=total_in,
                    output_tokens=total_out,
                    estimated_usd=estimated,
                    used_web=bool(use_web and self.settings.cloud_web_search),
                    tool_calls=total_tool_calls,
                )

            except Exception as exc:
                elapsed_ms = round(
                    (monotonic() - started) * 1000
                )
                error_code, safe_message, provider_error_code, retryable = (
                    self._classify_cloud_error(exc)
                )
                if error_code == "OPENAI_AUTH_INVALID":
                    self._client = None

                self.events.emit(
                    "CLOUD_ERROR",
                    error=error_code,
                    elapsed_ms=elapsed_ms,
                )
                return CloudAnswer(
                    ok=False,
                    text=safe_message,
                    elapsed_ms=elapsed_ms,
                    error=error_code,
                    provider_error_code=provider_error_code,
                    retryable=retryable,
                )
