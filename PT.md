[produção temática]:

1. Contexto

A gestão de riscos compreende o conjunto de práticas destinadas a identificar, mensurar, monitorar e controlar os riscos aos quais uma instituição está exposta. Nesse contexto, a modelagem de riscos utiliza dados, métodos estatísticos e técnicas de aprendizado de máquina para representar e quantificar fenômenos associados a esses riscos, apoiando sua avaliação e acompanhamento.

Entre os diferentes tipos de risco, destaca-se o risco de crédito, relacionado à possibilidade de ocorrência de perdas decorrentes do não cumprimento de obrigações financeiras por uma contraparte. Um dos instrumentos utilizados para sua mensuração é a construção de modelos capazes de estimar a probabilidade de default (PD), isto é, a probabilidade de ocorrência de inadimplência em determinado horizonte de análise.

Entretanto, a gestão adequada dos modelos de risco não se encerra em seu desenvolvimento. É necessário assegurar que o modelo permaneça adequado ao longo do tempo, por meio do acompanhamento de seu desempenho, da qualidade dos dados utilizados e de eventuais alterações no comportamento da população analisada. Dessa forma, a monitoração contínua de modelos depende não apenas da construção de modelos preditivos, mas também da capacidade de organizar dados, garantir rastreabilidade, automatizar processos e elaborar e acompanhar indicadores de desempenho ao longo do tempo.

2. Objetivo

Considerando esse contexto, utilize a base dados_credito.csv para desenvolver uma solução em Python que estime a probabilidade de default dos registros da base e proponha uma estratégia de acompanhamento contínuo do desempenho do modelo.
Além da construção do modelo preditivo, espera-se que o candidato demonstre capacidade de estruturar um fluxo analítico completo, contemplando aspectos de engenharia de dados, governança e monitoração de performance.
Identifique e registre as limitações do desafio enfrentado e quais foram as estratégias utilizadas para superação.

3. Dados

Abaixo, a relação das variáveis presentes na base fornecida para a elaboração da produção temática. O candidato não precisará utilizar todas as variáveis, devendo a escolha também constar embasada no trabalho.

4. Atividades Esperadas

4.1. Análise e Engenharia dos Dados

Realize uma análise exploratória da base de dados, identificando:

Estrutura e qualidade dos dados;
Valores ausentes e inconsistências;
Possíveis problemas de qualidade;
Distribuição da variável-alvo;
Variáveis potencialmente relevantes para a previsão de default.
Análise do comportamento das variáveis
Adicionalmente, apresente uma proposta de preparação dos dados abordando:

Tratamentos realizados;
Estruturação do pipeline de processamento;
Regras de transformação adotadas;
Estratégias para garantir reprodutibilidade do processo.

4.2. Construção do Modelo

Desenvolva um modelo para estimativa da probabilidade de default, contemplando:

Justificativa da técnica escolhida;
Processo de treinamento;
Análise e ajuste de hiperparâmetros;
Métricas utilizadas para avaliação.

4.3. Explicabilidade

Apresente métodos que permitam compreender o comportamento do modelo, incluindo:

Variáveis mais relevantes;
Impacto das principais características nas previsões;
Interpretação dos resultados gerados.

4.4. Monitoração de Performance

Considerando que o modelo será utilizado continuamente, proponha uma estratégia de monitoração contemplando:

Métricas de desempenho a serem acompanhadas;
Indicadores de estabilidade da população;
Indicadores de estabilidade das variáveis;
Possíveis sinais de degradação do modelo;
Critérios para acionamento de revisão ou retreinamento.
3.5. Arquitetura da Solução

Descreva como você estruturaria uma solução para execução recorrente do processo, abordando minimamente:

Organização dos componentes do código;
Separação entre ingestão, tratamento, treinamento e monitoração;
Estratégias para armazenamento de métricas;
Possibilidades de automação e escalabilidade.
Não é necessário implementar integralmente a arquitetura proposta, mas espera-se que o candidato apresente uma visão de como a solução poderia ser operacionalizada em ambiente corporativo.

Identifique e registre as limitações do desafio enfrentado e quais foram as estratégias utilizadas para superação.

5. Entregáveis:

Código-fonte reprodutível em Python (.py e/ou notebooks);
Documento (em pdf) estruturado discorrendo acerca de todos os pontos acima mencionados (deve-se apresentar claramente as decisões adotadas devidamente embasadas, as evidências das análises realizadas, a proposta de monitoração contínua e as conclusões e recomendações para uso e acompanhamento do modelo).
Apresentação em slides, elaborada em PowerPoint ou ferramenta equivalente, a ser entregue em formato PDF para posterior apresentação (Tempo de apresentação estimado em 10 minutos).

Concluí a produção temática. O relatório aborda análise dos dados, engenharia e pipeline, comparação de modelos, explicabilidade, monitoração, arquitetura proposta e limitações.

Entregáveis

Relatório técnico em PDF
Apresentação em PDF — 8 slides
Apresentação editável em PowerPoint
Código-fonte Python
Métricas e parâmetros
Dependências fixadas
Na base de 25.000 registros, a taxa de default foi 6,14%. A regressão logística foi selecionada; no teste estratificado, obteve ROC AUC 0,847, Average Precision 0,314 e Brier 0,0489. No limiar ilustrativo de 0,50, o recall foi baixo (6,5%), então o limiar não deve ser tratado como decisão operacional.

A validação foi retrospectiva e aleatória: como a base não contém datas nem horizonte explícito de default, não comprova desempenho futuro nem permite medir drift temporal. Por isso, o relatório recomenda validação temporal e governança antes de qualquer uso decisório.

Para reproduzir: python -m pip install -r requirements.txt e depois python producao_tematica.py --data dados_credito.csv --output resultados.