from __future__ import annotations

import re
import unicodedata


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def guard_unverified_local_action_claim(
    user_text: str,
    answer: str,
    *,
    successful_tool_calls: int,
) -> tuple[str, bool]:
    """Block claims/promises of local execution when no tool succeeded.

    0.27.8 v9 broadens the original completion-only guard.  The previous guard
    caught statements such as "executado", but still allowed the model to say
    "estou a executar", "vou verificar" or "aguarde" even though no tool had
    been called.  Those are equally misleading in a synchronous local agent.

    The guard remains narrow: it activates only when the OWNER's current turn is
    an operational request (including an explicitly named registered-tool style
    request) and there is zero successful tool evidence in this request.
    """
    if int(successful_tool_calls) > 0:
        return str(answer or ""), False

    request = _normalize(user_text)
    response = _normalize(answer)
    if not request or not response:
        return str(answer or ""), False

    local_action = bool(re.search(
        r"(?:^|\b)(abre|abra|abrir|agrade|fecha|feche|fechar|liga|ligue|desliga|desligue|"
        r"ativa|ative|desativa|desative|inicia|inicie|lanca|lance|executa|execute|executar|"
        r"corre|correr|chama|chamar|invoca|invocar|usa|usar|utiliza|utilizar|"
        r"testa|testar|analisa|analisar|verifica|verificar|consulta|consultar|"
        r"escreve|escrever|digita|digitar|clica|clicar|foca|focar|move|mover|descreve|descrever|"
        r"prime|premir|pressiona|pressionar|muda|altera|define|poe|coloca|bloqueia|tranca)(?:\b|$)",
        request,
    ))
    visual_request = bool(
        re.search(r"\b(?:ecra|ecrã|tela|screen)\b", request)
        and re.search(r"\b(?:analisa|analisar|descreve|descrever|ve|ves|vês|ver|olha)\b", request)
    )
    if not local_action and not visual_request:
        return str(answer or ""), False

    # Claims that an action already completed.
    completion_claim = bool(re.search(
        r"\b(aberto|aberta|fechado|fechada|ligado|ligada|desligado|desligada|"
        r"ativado|ativada|desativado|desativada|iniciado|iniciada|executado|executada|"
        r"concluido|concluida|definido|definida|alterado|alterada|bloqueado|bloqueada|"
        r"feito|feita|escrevi|digitei|cliquei|foquei|movi|pressionei|premi|analisei|consultei|"
        r"abri|fechei|executei)\b",
        response,
    ))

    # Claims that execution is happening now or will happen asynchronously.
    in_progress_or_future_claim = bool(re.search(
        r"\b(?:estou|estamos)\s+(?:a\s+)?(?:executar|executando|verificar|verificando|"
        r"consultar|consultando|obter|obtendo|processar|processando|analisar|analisando|"
        r"carregar|carregando)\b|"
        r"\b(?:vou|irei|vamos)\s+(?:agora\s+)?(?:executar|verificar|consultar|obter|"
        r"processar|analisar|apresentar|retornar|devolver|mostrar)\b|"
        r"\b(?:aguarde|por favor aguarde|so um momento|só um momento)\b|"
        r"\b(?:assim que|quando)\s+(?:terminar|concluir)\b",
        response,
    ))

    visual_claim = bool(visual_request and re.search(
        r"\b(?:estou a ver|vejo|o ecra mostra|o ecrã mostra|a tela mostra|no ecra ha|no ecrã há|no ecrã vejo)\b",
        response,
    ))

    # A model-emitted pseudo tool call is not execution evidence. Never expose
    # tool-call XML/JSON as if the Core had executed it.
    pseudo_tool_call = bool(
        re.search(r"<tool_call>.*?</tool_call>", str(answer or ""), flags=re.IGNORECASE | re.DOTALL)
        or re.search(r'\{\s*["\']name["\']\s*:\s*["\'][a-z_][a-z0-9_]*["\']\s*,\s*["\']arguments["\']', str(answer or ""), flags=re.IGNORECASE | re.DOTALL)
    )

    if not (completion_claim or in_progress_or_future_claim or visual_claim or pseudo_tool_call):
        return str(answer or ""), False

    return (
        "Não executei essa ação: nenhuma ferramenta local terminou com sucesso neste pedido.",
        True,
    )
