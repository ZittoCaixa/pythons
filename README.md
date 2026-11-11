# Probabilidade de default — guia do projeto

## Para que serve

Este projeto é um **protótipo analítico** para estudar a probabilidade de default (PD) em solicitações de crédito. Ele lê uma base histórica, prepara os dados, compara dois modelos, escolhe um modelo com base em validação cruzada e gera resultados, gráficos, relatório e apresentação.

Para a área negocial, o objetivo futuro seria apoiar a priorização de análises e o acompanhamento do risco de uma carteira. A PD é uma estimativa estatística: **não é uma decisão de aprovar ou recusar crédito, nem uma garantia de inadimplência**. O projeto atual foi feito para análise retrospectiva e não está conectado a sistemas ou dados atualizados da operação.

> **Importante:** não utilizar o resultado atual para conceder, limitar ou negar crédito. A base não informa a data de cada operação nem o horizonte usado para definir default. Portanto, os resultados não demonstram como o modelo funcionará em períodos futuros. Antes de qualquer uso decisório, são necessárias validação temporal, avaliação de calibração e equidade, definição do horizonte de risco, aprovação de governança e controles operacionais.

## O que o fluxo faz

Ao executar o programa, ele:

1. Lê o CSV e confere a presença das colunas necessárias e se o alvo contém apenas `0` e `1`.
2. Converte variáveis numéricas e prepara valores ausentes dentro do pipeline, sem ajustar os tratamentos usando o conjunto de teste.
3. Separa os dados em treino e teste de forma estratificada (80%/20%), com semente fixa para reprodutibilidade.
4. Compara regressão logística e Random Forest, ajustando hiperparâmetros em validação cruzada. A escolha usa Average Precision, que é mais informativa que acurácia quando há poucos defaults.
5. Avalia o modelo escolhido no teste e estima PD para cada registro desse conjunto.
6. Gera tabelas, gráficos, um modelo serializado, um relatório PDF e uma apresentação em PDF e PowerPoint.

Na base fornecida, com 25.000 registros, a taxa observada de default foi de aproximadamente 6,14%. A execução selecionou a regressão logística; no teste aleatório, obteve ROC AUC de aproximadamente 0,847 e Average Precision de 0,314. Esses números descrevem apenas este experimento e **não são metas de produção nem evidência de desempenho futuro**. No limiar ilustrativo de 0,50, o recall foi baixo; o limiar não foi otimizado para uso negocial.

## Arquivos do projeto

Na pasta principal:

- `dados_credito.csv`: base de entrada usada no exercício. Trate-a como dado potencialmente sensível e não a compartilhe sem autorização.
- `producao_tematica.py`: código que executa o fluxo completo.
- `requirements.txt`: versões das bibliotecas Python utilizadas.
- `PT.md`: enunciado da produção temática.
- `README.md`: este guia.

## Requisitos

- Windows com PowerShell.
- Python instalado. O código foi executado neste projeto com Python 3.15.2.
- Acesso à internet durante a instalação inicial das bibliotecas.
- Espaço em disco para os arquivos gerados na pasta de resultados.

## Como instalar e executar

Abra o PowerShell na pasta do projeto (a pasta que contém `producao_tematica.py`) e execute:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe producao_tematica.py --data .\dados_credito.csv --output .\resultados
```

O ambiente virtual `.venv` isola as dependências do projeto. Os comandos usam diretamente o Python desse ambiente, então não é necessário ativá-lo. Se já houver um ambiente virtual ativado, também é possível usar `python -m pip install -r requirements.txt` e `python producao_tematica.py --data .\dados_credito.csv --output .\resultados`.

Para usar outra base ou pasta de saída, altere os caminhos:

```powershell
.\.venv\Scripts\python.exe producao_tematica.py --data .\entrada\minha_base.csv --output .\saidas
```

O programa também aceita caminhos absolutos. Se não forem informados argumentos, usa `dados_credito.csv` e `resultados` por padrão.

### Executar novamente

Uma nova execução atualiza arquivos de mesmo nome na pasta de saída. Use uma pasta diferente se precisar preservar resultados anteriores. A semente fixa torna os splits e o treinamento reproduzíveis para a mesma base e as mesmas versões das bibliotecas.

## Requisitos da base de entrada

O arquivo deve ser um CSV legível pelo pandas, preferencialmente codificado em UTF-8. Precisa conter estas colunas:

| Coluna | Uso |
|---|---|
| `cliente` | Identificador preservado para associar a previsão ao registro; não é usado pelo modelo. |
| `tipo_emprego` | Atributo categórico usado pelo modelo. |
| `tempo_conta_bancaria` | Numérico: tempo de relacionamento bancário. |
| `renda_mensal` | Numérico: renda informada. |
| `qtde_outros_emprestimos_atual` | Numérico: quantidade de outros empréstimos. |
| `valor_mensal_prestacoes_outros_emprestimos_atual` | Numérico: valor das prestações mensais existentes. |
| `taxa_uso_credito` | Numérico: utilização de crédito. |
| `consultas_credito_ultimos_6meses` | Numérico: consultas recentes de crédito. |
| `pagamentos_atrasados_ultimos_12meses` | Numérico: atrasos recentes. |
| `valor_emprestimo_solicitado` | Numérico: valor solicitado. |
| `prazo_emprestimo_solicitado` | Numérico: prazo solicitado. |
| `objetivo_empréstimo_solicitado` | Atributo categórico: finalidade do empréstimo. |
| `existencia_garantia` | Atributo categórico: existência de garantia. |
| `marcacao_default` | Alvo histórico, obrigatório para treinar e avaliar; deve ser `0` ou `1`. |

Na base do exercício também existem `idade`, `genero`, `estado_civil`, `tipo_cidade` e `estado`. Elas não são utilizadas no modelo por decisão inicial de minimização de dados e governança, incluindo a redução do uso de potenciais proxies demográficos ou geográficos. Essa escolha precisa ser revista e validada pelas áreas de Risco, Compliance e Jurídico no contexto de uma instituição.

Valores ausentes nos atributos usados são tratados pelo pipeline. Linhas com alvo ausente ou diferente de `0`/`1` impedem a execução, em vez de serem silenciosamente descartadas. O CSV de entrada precisa ter a coluna `marcacao_default`: **o script não oferece, por enquanto, um comando separado para pontuar uma base nova sem alvo**.

## Arquivos gerados em `resultados`

O fluxo gera todos os itens abaixo em uma única execução:

| Arquivo | O que contém |
|---|---|
| `relatorio_producao_tematica.pdf` | Análise, decisões de dados, modelos, métricas, explicabilidade, monitoração proposta, arquitetura e limitações. |
| `apresentacao_producao_tematica.pdf` | Apresentação resumida em PDF, com 8 slides. |
| `apresentacao_producao_tematica.pptx` | Versão editável da apresentação. |
| `metricas.json` | Perfil da base, versões de bibliotecas, hiperparâmetros, métricas de validação cruzada e teste. |
| `predicoes_teste.csv` | Identificador, default observado, PD estimada e classificação ilustrativa no limiar 0,50 para os registros do conjunto de teste. |
| `pipeline_serializado.joblib` | Pipeline do melhor modelo treinado, incluindo tratamento de dados e estimador. É um artefato técnico; carregar apenas de fonte confiável e em ambiente compatível. |
| `perfil_numerico.csv` | Ausências e medianas das variáveis numéricas, separadas por classe. |
| `perfil_categorico.csv` | Volume e taxa observada de default por categoria; categorias com menos de 100 registros são omitidas. |
| `importancia_permutacao.csv` | Impacto global de embaralhar cada variável na Average Precision. |
| `psi_referencia.csv` | PSI das variáveis numéricas entre treino e teste do split aleatório. É uma comparação ilustrativa, não drift temporal. |
| `distribuicao_alvo.png` | Gráfico das quantidades de registros por classe do alvo. |
| `valores_ausentes.png` | Gráfico da proporção de ausências nas variáveis usadas. |
| `curva_roc.png` | Curva ROC do modelo escolhido no conjunto de teste. |
| `calibracao.png` | Comparação entre PD prevista e frequência observada no teste. |
| `importancia_permutacao.png` | Gráfico da importância global por permutação. |
| `efeito_medio_variaveis.png` | Gráficos de dependência parcial para variáveis numéricas relevantes; representam associações estimadas pelo modelo, não causalidade. |

Para uma leitura gerencial, comece pelo relatório e pelos PDFs da apresentação. O `metricas.json` e os CSVs são evidências analíticas para acompanhamento técnico; o arquivo `.joblib` não é um aplicativo e, isoladamente, não implanta ou monitora o modelo.

## Como interpretar o monitoramento

O programa calcula métricas de teste e um PSI entre as amostras de treino e teste. O relatório também propõe uma rotina futura:

- Por lote: validar esquema, campos ausentes, faixas e categorias inesperadas.
- Semanalmente: observar a distribuição de scores e qualidade de entrada.
- Mensalmente, quando os resultados de default já estiverem maduros: avaliar ROC AUC, Average Precision, recall/precisão no limiar aprovado e calibração.
- Acompanhar PSI e resultados por grupos permitidos pela política e pela legislação, com análise de impacto e governança.
- Investigar alertas antes de qualquer retreino; nova versão exige validação independente e aprovação.

Os limites de PSI e de queda de desempenho descritos no relatório são **propostas iniciais de alerta**, não regras já conectadas a uma rotina automática. O projeto não agenda execuções, não envia alertas, não acessa bases de produção e não retreina continuamente. O PSI fornecido compara um split aleatório da mesma base, portanto não mede mudança ao longo do tempo.

## Próximos passos antes de uso na operação

1. Definir formalmente o evento de default e o horizonte da probabilidade.
2. Obter uma base com datas e resultados observados após a originação para validação temporal.
3. Avaliar qualidade, calibração, estabilidade, equidade e impacto econômico, inclusive por segmentos relevantes.
4. Definir o uso negocial, o limiar e os custos de falsos positivos e falsos negativos com as áreas responsáveis.
5. Implementar scoring de dados novos, monitoramento em ambiente corporativo, controle de versões, trilha de auditoria, acessos e plano de contingência.
6. Submeter o modelo e seu uso à validação independente e aos fóruns de aprovação aplicáveis.

