# JARVIS Core 0.27.8 — Hard Audit Remediation

Data: 04-09-2026  
Âmbito: auditoria documental e logs manuais fornecidos pelo OWNER.

## Fontes revistas

- 04-09-2026 Jarvis Log de Aprendizagem.txt
- JARVIS_Auditoria_Aprendizagem_04-09-2026.docx
- JARVIS_ERRORS_MANUAL_AUDIT_01.txt a JARVIS_ERRORS_MANUAL_AUDIT_05.txt
- JARVIS_Fontes_Nao_Aprendidas_Reteste_04-09-2026.docx

Os documentos foram tratados como evidência de testes, não como instruções executáveis.

## Correções implementadas

### Aprendizagem Web e proveniência

- URLs canónicos removem parâmetros de rastreio e fragmentos sem alterar o URL funcional usado no acesso.
- Identidade SHA-256 por fonte e deduplicação de aprendizagem por tópico/fonte.
- Inferência temática corrigida para domínios `.us`, `.info`, `.io`, `.dev` e fontes conhecidas dos retestes.
- Ligação temporária (máximo de cinco minutos) entre um objetivo explícito de aprendizagem e um URL enviado no turno seguinte.
- Leitura direta de fontes HTML/texto, JSON e PDF; PDFs com MIME genérico são aceites quando a extensão é `.pdf`.
- Resumos sem evidência, mensagens de aplicação/landing page e blocos truncados deixam de ser guardados.
- Diagnóstico HTTP distingue o status e indica se a falha é repetível.
- Ranking ponderado pelo tópico, consulta e identidade da fonte. Uma palavra incidental num resumo não transforma Nmap em aprendizagem sobre TCP/DNS.
- Perguntas de proveniência usam o registo da resposta imediatamente anterior e são classificadas como `PROVENANCE_PREVIOUS`, nunca `ACCEPT_PREVIOUS`.
- Mensagens distinguem permissão persistente de execução limitada atual.

### Código e apresentação

- Pedidos de programação pura deixam de expor ferramentas de ficheiros/apps por colisão de palavras.
- Blocos Python são validados com `ast.parse`, sem executar o código.
- Um bloco inválido recebe uma única tentativa de reparação pelo cérebro local; se continuar inválido, é rejeitado em vez de apresentado como executável.
- Indentação e conteúdo dentro de blocos/inline code permanecem protegidos.
- Entidades HTML e escapes Markdown são reparados apenas na prosa.
- Novas normalizações PT-PT cobrem `arquivo`, `gerenciador`, `retorna`, `funcionando` e casos observados.
- Prefixos como `21.`, `[21]`, `T21` e `Teste 21:` são removidos antes do routing.

### Desktop, aplicações e segurança

- Janela em primeiro plano usa `desktop_observe`.
- “Volta à janela X” executa `desktop_focus_window` e só confirma com resultado real.
- “Bloqueia a aplicação X” é recusado por design e nunca chama `open_application`.
- Abertura de aplicações é idempotente: se já estiver a correr, não lança outra instância.
- Novas aberturas devolvem `effect_verified`; a resposta distingue “confirmado” de “pedido enviado ainda não confirmado”.
- Perguntas CPU/RAM/GPU usam uma única amostra e devolvem as três métricas.
- Processo que mais consome memória e consulta `calc.exe` usam `list_top_processes`.
- Estado do Cyber Range e classificação de IP usam as ferramentas reais. Zero âmbitos LAB implica “não configurado/não pronto”.
- Mantido ZERO WDAC/App Control enforcement; nenhum controlo de segurança foi enfraquecido.

### Confirmações, ficheiros e Planner

- “Autorizo”/“não autorizo” passam a consumir uma única ação local pendente inequívoca, mantendo separadas as filas SecurityPolicy e Autonomy.
- Frases com âmbito são comparadas com a ação pendente; ambiguidades não executam nada.
- Corrigidos os padrões de confirmação tokenizada.
- Pesquisa de PDFs “com X no nome” aplica filtro real ao nome.
- Resultados locais mantêm continuidade para caminhos, ficheiro mais recente e leitura do primeiro documento.
- “Procura X no computador inteiro” usa pesquisa local, não telemetria/Web.
- Planner mantém o ID real do plano entre turnos, permite leitura, próximo passo e execução limitada a um passo.
- Alterações de passo não suportadas e criação de ficheiro sem ferramenta segura falham de forma explícita, sem falso sucesso.
- `/qquit` é aceite como alias seguro de encerramento.

## Validação

- Compilação Python dos módulos alterados: OK.
- Testes focados de aprendizagem, segurança, desktop, aplicações, código, linguagem, ficheiros, Planner e follow-up: OK.
- Suíte completa: **948 testes executados, 948 aprovados**.
- `git diff --check`: sem erros de whitespace; apenas avisos normais de conversão LF/CRLF no Windows.

## Fronteiras deliberadas e reteste real

Não foi adicionada escrita arbitrária de ficheiros nem edição manual de passos do Planner, porque o Core não possui atualmente ferramentas confinadas e confirmadas para essas mutações. Os pedidos agora falham de forma verdadeira e segura. Para transformar essas limitações em capacidades, será necessário desenhar ferramentas específicas com diretórios permitidos, confirmação OWNER, escrita atómica e verificação posterior.

Depois de instalar esta atualização, recomenda-se repetir no terminal real os roteiros dos cinco logs, sobretudo microfone/voz, captura visual, foco de janelas e arranque automático, porque esses pontos dependem do estado do Windows e do hardware e não são integralmente simuláveis por testes unitários.