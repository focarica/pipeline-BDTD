# Benchmark RAG — 30 perguntas

Gabarito do avaliador: não incluir este arquivo no índice nem nos prompts do sistema avaliado.

Fontes: `evidence.json`. Protocolo e métricas: `README.md`.

## R01 — resultado_condicional

No DustAI, quais foram os coeficientes de Pearson antes e depois da calibração para MP10 e MP2,5, no cenário com duas semanas de dados? Identifique o cenário para não confundi-lo com todas as coletas do estudo.

**Resposta de referência:** No cenário de calibração com duas semanas de dados, o Pearson de MP10 passou de 0,48 a 0,74 e o de MP2,5, de 0,69 a 0,79.

**Itens avaliados:**
- MP10: 0,48 para 0,74
- MP2,5: 0,69 para 0,79
- Resultado do modelo de calibração gerado com duas semanas de dados; não de qualquer coleta indiscriminadamente

**Erros críticos:**
- Trocar as duas frações de material particulado
- Apresentar correlação como acurácia de classificação

**Evidências:** (dust.001)

## R02 — calculo_derivado

A partir do resultado de duas semanas do DustAI, calcule a redução percentual do MAE de MP10 e de MP2,5. Mostre a fórmula e não confunda queda absoluta com percentual.

**Resposta de referência:** Usando (MAE inicial − MAE final)/MAE inicial × 100: MP10 teve redução de 58,45% e MP2,5 de 33,63%. As quedas absolutas foram 9,68 e 1,14, não 9,68% e 1,14%.

**Itens avaliados:**
- MAE MP10: 16,56 para 6,88
- MAE MP2,5: 3,39 para 2,25
- Fórmula: (antes - depois) / antes × 100
- Reduções aproximadas de 58,45% e 33,63%, respectivamente; tolerância de 0,1 ponto percentual

**Erros críticos:**
- Usar o MAE final como denominador
- Dizer que o erro caiu a zero

**Evidências:** (dust.001)

## R03 — arquitetura_e_condicoes

Como o DustAI transporta as medições e onde realiza a calibração? Quais fatores ambientais motivam esse processamento? Separe comunicação, processamento e influência ambiental.

**Resposta de referência:** O transporte usa LoRaWAN para levar as medições à Internet. A calibração usa modelos de AM na nuvem, buscando corrigir leituras influenciadas, entre outros fatores, por temperatura e umidade.

**Itens avaliados:**
- Transmissão em tempo real pela Internet usando LoRaWAN
- Modelo de aprendizado de máquina hospedado na nuvem
- Temperatura e umidade afetam as leituras dos sensores

**Erros críticos:**
- Dizer que LoRaWAN é o algoritmo de calibração
- Afirmar que a calibração é feita exclusivamente no sensor

**Evidências:** (dust.000)

## R04 — procedimento_experimental

Na comparação DustAI–BAM 1020, por que o maior número de leituras válidas do dispositivo não foi usado integralmente na comparação? Quantas amostras horárias pareadas foram obtidas e a quantos dias isso corresponde aproximadamente?

**Resposta de referência:** A comparação exigiu horas coincidentes nos dois equipamentos. O pareamento resultou em 679 amostras horárias, cerca de 28 dias; as demais leituras não constituíam pares temporais para essa análise.

**Itens avaliados:**
- Pareamento por horas iguais entre os equipamentos
- 679 amostras horárias
- Aproximadamente 28 dias
- Ter mais leituras disponíveis não equivale a ter mais pares simultâneos comparáveis

**Erros críticos:**
- Usar 1.289 como número de pares
- Confundir as amostras com 679 dias

**Evidências:** (dust.035)

## R05 — mecanismo

O que o PersonaReAct acrescenta ao ReAct, em qual ponto do fluxo e com qual informação do usuário? Ele substitui o ciclo de raciocínio e ação?

**Resposta de referência:** O Tailor adapta a resposta final ao perfil funcional do usuário. É uma etapa adicional de personalização; o ciclo original de raciocínio e ação do ReAct é preservado.

**Itens avaliados:**
- Função/módulo Tailor
- Etapa final de adaptação da resposta
- Adaptação segundo o perfil funcional, características e necessidades do usuário
- Preserva o ciclo original de raciocínio e ação

**Erros críticos:**
- Descrever Tailor como fine-tuning dos pesos
- Afirmar que elimina a recuperação ou o ciclo ReAct

**Evidências:** (persona.002)

## R06 — desenho_experimental

No Experimento 2 do PersonaReAct, descreva a comparação com Tailor ligado e desligado: quantas perguntas neutras, quantos perfis, quantas saídas por pergunta e quantas saídas no total? Reconcilie a contagem com a descrição de 140 no texto.

**Resposta de referência:** São 20 perguntas e seis perfis: cada pergunta gera uma saída neutra e seis personalizadas. Isso produz sete saídas por pergunta e 140 ao todo. A expressão '140 conjuntos' no texto deve ser lida com cautela: a multiplicação explicitada é 20 × 7.

**Itens avaliados:**
- 20 perguntas neutras
- 6 perfis
- 1 resposta neutra com Tailor desligado e 6 personalizadas com Tailor ligado
- 7 saídas por pergunta e 140 saídas ao todo (20 × 7); não 140 × 7

**Erros críticos:**
- Contabilizar 980 respostas
- Omitir a condição com Tailor desligado

**Evidências:** (persona.053)

## R07 — controle_de_confundidores

Como o Experimento 2 do PersonaReAct tenta separar o efeito do perfil do efeito do conteúdo da pergunta? Quais modelos e temperatura foram usados nesse experimento?

**Resposta de referência:** As adaptações mudam estilo e tom, não o conteúdo nem a intenção. As versões personalizadas são comparadas à neutra. O experimento usa o3-mini e GPT-4.1 mini com temperatura 1.

**Itens avaliados:**
- Perguntas adaptadas em estilo/tom preservando conteúdo e intenção
- Comparação das versões personalizadas com resposta neutra
- o3-mini e GPT-4.1 mini
- temperature = 1

**Erros críticos:**
- Usar perguntas de assuntos diferentes para cada perfil
- Atribuir temperatura zero ao experimento

**Evidências:** (persona.053)

## R08 — contradicao_documental

Sobre o SAAL, o resumo dos metadados e o texto do resumo no corpus dão a mesma contagem de subcaracterísticas e recomendações? Apresente ambas e explique se é possível declarar uma única contagem definitiva apenas com essas duas evidências.

**Resposta de referência:** Não coincidem: os metadados mencionam 10 subcaracterísticas e 55 recomendações; o resumo processado menciona 10 principais, 7 secundárias e 48 recomendações. Essas evidências não permitem decidir a contagem definitiva nem inferir automaticamente uma mudança de versão.

**Itens avaliados:**
- Metadados: duas categorias, dez subcaracterísticas e 55 recomendações
- Texto processado: dez subcaracterísticas principais, sete secundárias e 48 recomendações
- Reconhecer divergência entre representações/fontes
- Não resolver por soma ou preferência arbitrária; consultar versão original ou esclarecimento adicional

**Erros críticos:**
- Ocultar a divergência
- Somar 48 + 7 para justificar 55 como se fossem a mesma entidade

**Evidências:** (saal.abstract) AND (saal.001)

## R09 — metodologia

No SAAL, que métodos apoiaram a construção do catálogo, qual representação estruturada foi utilizada e quem participou de sua validação? Diferencie construção, representação e validação.

**Resposta de referência:** O trabalho articula Snowballing e Grounded Theory para construir o catálogo, representa o RNF de segurança com SIG e valida a proposta com especialistas, incluindo engenheiros/desenvolvedores, por entrevistas e questionários.

**Itens avaliados:**
- Snowballing e Grounded Theory na abordagem de construção
- Softgoal Interdependency Graph (SIG)
- Validação com especialistas/engenheiros de software e desenvolvedores, por entrevistas e questionários segundo os metadados

**Erros críticos:**
- Descrever validação como ensaio clínico com idosos
- Confundir SIG com um classificador treinado

**Evidências:** (saal.001) AND (saal.abstract)

## R10 — dados_e_metodos

No sistema de recomendação para nutrição oncológica, quais são as duas abordagens computacionais e como são obtidos os perfis dos pacientes usados na proposta? Qual é o papel do profissional de nutrição?

**Resposta de referência:** O sistema usa TOPSIS e NSGA-II, combinando dados nutricionais dos alimentos com perfis de pacientes gerados sinteticamente. A proposta complementa o trabalho dos profissionais de nutrição.

**Itens avaliados:**
- TOPSIS e NSGA-II
- Perfis personalizados gerados sinteticamente/hipoteticamente por simulador
- Dados nutricionais de alimentos
- Ferramenta complementar ao trabalho do profissional, não substituição clínica autônoma

**Erros críticos:**
- Afirmar que todos os perfis são prontuários de pacientes reais
- Apresentar o sistema como substituto validado do nutricionista

**Evidências:** (nutrition.000 OR nutrition.041)

## R11 — limite_da_conclusao

O fato de o sistema de nutrição oncológica gerar dietas que atendem metas e restrições permite concluir que houve melhora clínica de pacientes reais? Explique a diferença entre o resultado computacional descrito e essa conclusão.

**Resposta de referência:** Não. O resultado descrito é computacional e utiliza perfis sintéticos. Satisfazer metas e restrições não demonstra, por si, ganho clínico em pacientes reais; não se deve inventar um ensaio clínico.

**Itens avaliados:**
- Resultado relatado é a geração de recomendações que atendem metas e restrições
- Perfis sintéticos/hipotéticos
- Essas evidências não demonstram melhora clínica em pacientes reais
- Validação clínica adicional seria necessária para tal afirmação

**Erros críticos:**
- Inventar redução de mortalidade
- Converter viabilidade computacional em eficácia clínica comprovada

**Evidências:** (nutrition.000 OR nutrition.041)

## R12 — resultado_condicional

Na tese sobre VFC e estágios de COVID-19, qual foi o algoritmo principal e quais foram os dois valores de desempenho apresentados no resumo? Que informação adicional distingue os dois cenários?

**Resposta de referência:** O resumo seleciona árvore de decisão e relata 77% em geral, chegando a 96,7% quando há informação de infecção recente. A terminologia 'precisão' no resumo em português e 'accuracy' no inglês deve ser preservada com cautela, sem inferir precision técnica.

**Itens avaliados:**
- Árvore de decisão
- 77% de desempenho médio geral segundo o resumo
- 96,7% quando havia informação sobre infecções recentes por COVID-19
- Manter explícita a condição, sem tratar 96,7% como desempenho irrestrito

**Erros críticos:**
- Dizer que 96,7% é o resultado sem informação adicional
- Afirmar que o resumo demonstra sensibilidade de 96,7%

**Evidências:** (covid.000 OR covid.001)

## R13 — calculo_e_interpretacao

No resumo da tese de VFC/COVID-19, a passagem de 77% para 96,7% representa quanto em pontos percentuais e em aumento relativo? Por que o cálculo sozinho não prova que um algoritmo novo superou o anterior?

**Resposta de referência:** A diferença é 19,7 pontos percentuais; relativamente a 77%, é 19,7/77 × 100 ≈ 25,58%. Os números envolvem disponibilidade diferente de informação, não demonstram isoladamente uma troca superior de algoritmo.

**Itens avaliados:**
- 19,7 pontos percentuais
- Aumento relativo de aproximadamente 25,58%; tolerância 0,1 ponto percentual
- O cenário de 96,7% dispõe de informação sobre infecção recente
- Não inferir comparação controlada de algoritmos apenas desses números

**Erros críticos:**
- Confundir 19,7 pontos percentuais com 19,7% relativo
- Omitir a diferença de informação entre cenários

**Evidências:** (covid.000 OR covid.001)

## R14 — fluxo_de_dados

Na tese de VFC/COVID-19, quais estados de saúde são investigados e como os dados vão da coleta à resposta disponibilizada?

**Resposta de referência:** O trabalho investiga saudáveis, COVID-positivos e COVID longa. Um oxímetro automatizado coleta/transmite VFC para um servidor remoto, e um sistema web apresenta o monitoramento em tempo real.

**Itens avaliados:**
- Indivíduos saudáveis, positivos para COVID-19 e com COVID longa
- Oxímetro automatizado coleta e transmite dados de VFC
- Processamento em servidor remoto
- Sistema web de monitoramento em tempo real

**Erros críticos:**
- Afirmar que o pipeline depende exclusivamente de exames laboratoriais
- Diagnosticar o usuário da aplicação com base apenas no relato do estudo

**Evidências:** (covid.000 OR covid.001)

## R15 — dados_experimentais

Na dissertação de estratégias híbridas para preços de ações na B3, qual foi a fonte dos dados, o intervalo temporal e a frequência de amostragem? Que três representações foram usadas para alimentar CNNs?

**Resposta de referência:** Os dados vieram do investing.com, de 2013 a 2023, em frequência diária. Para CNNs foram construídas representações em blocos, linhas e velas.

**Itens avaliados:**
- investing.com
- 2013 a 2023
- Amostragem diária
- Blocos, gráfico de linhas e gráfico de velas/candlestick

**Erros críticos:**
- Trocar a frequência diária por intradiária
- Dizer que os dados são cotações futuras de 2026

**Evidências:** (stocks.000 OR stocks.001)

## R16 — resistencia_a_premissa_falsa

O título da dissertação sobre redes híbridas e ações brasileiras prova que as redes híbridas tiveram os menores erros? Responda usando os resultados do resumo e separe erro de correlação.

**Resposta de referência:** Não. Apesar do título, o resumo destaca MLP e Bagging; a abordagem híbrida em blocos foi promissora pela correlação, mas não obteve os melhores erros. Esses critérios não devem ser confundidos.

**Itens avaliados:**
- Não: o resumo destaca MLP e Bagging nas métricas de erro
- Redes híbridas em blocos apresentaram correlações altas em geral, sem os melhores erros
- Correlação alta não equivale automaticamente a menor MAE/RMSE

**Erros críticos:**
- Escolher CNN-LSTM como vencedora apenas pelo título
- Apresentar promessa de lucro garantido

**Evidências:** (stocks.001)

## R17 — resumo_versus_tabela

O resumo da dissertação de ações menciona RMSE de Bagging abaixo de 0,7. A Tabela 23 permite estender isso a todas as bases e a ambas as análises? Use os valores de MGLU3 multivariada e VALE3 univariada para responder.

**Resposta de referência:** Não. A Tabela 23 contém 0,7084 para MGLU3 multivariada e 25,1407 para VALE3 univariada. Portanto, a síntese do resumo não pode ser universalizada; o resultado depende da base e do cenário.

**Itens avaliados:**
- Bagging multivariada em MGLU3: RMSE 0,7084
- Bagging univariada em VALE3: RMSE 25,1407
- A afirmação abaixo de 0,7 não vale literalmente para todas as bases/cenários
- Reportar a discrepância/limitação do resumo sem modificar os números

**Erros críticos:**
- Arredondar 0,7084 para justificar 'abaixo de 0,7'
- Usar Pearson no lugar de RMSE

**Evidências:** (stocks.001) AND (stocks.040) AND (stocks.041)

## R18 — comparacao_intradocumental

Na Tabela 23 da dissertação de ações, compare Bagging em VALE3 nas análises univariada e multivariada. Informe RMSE e Pearson de cada uma e interprete a diferença apenas no experimento relatado.

**Resposta de referência:** Em VALE3, o Bagging univariado tem RMSE 25,1407 e Pearson 0,2502; o multivariado, RMSE 0,2246 e Pearson 0,9998. O segundo foi melhor nesses indicadores do experimento, não uma garantia de ganhos financeiros.

**Itens avaliados:**
- VALE3 univariada: RMSE 25,1407 e Pearson 0,2502
- VALE3 multivariada: RMSE 0,2246 e Pearson 0,9998
- Multivariada tem menor RMSE e maior correlação nesse caso
- Sem generalizar para lucro, outros períodos ou todo mercado

**Erros críticos:**
- Inverter univariada e multivariada
- Interpretar 0,9998 como retorno financeiro

**Evidências:** (stocks.040) AND (stocks.041)

## R19 — escopo_amostral

No estudo de Didelphis aurita e T. cruzi, qual é o período e o tamanho aproximado da base geral descrita no resumo? Essa contagem pode ser atribuída automaticamente a D. aurita em todas as análises?

**Resposta de referência:** O resumo descreve mais de 3.000 pequenos mamíferos coletados entre 2003 e 2021. Essa base geral não equivale automaticamente ao N de D. aurita em cada análise; os subconjuntos precisam ser identificados.

**Itens avaliados:**
- Mais de 3.000 pequenos mamíferos
- Coletas entre 2003 e 2021 na Mata Atlântica
- Não confundir base geral de pequenos mamíferos com subconjunto de D. aurita
- Tabela específica de D. aurita mostra subconjunto por sexo/status, não toda a base

**Erros críticos:**
- Declarar que todas as 3.000 observações são D. aurita
- Tratar todos os registros como indivíduos infectados

**Evidências:** (ecology.abstract) AND (ecology.030 OR ecology.031)

## R20 — calculo_de_tabela

Na Tabela 1 de massa corporal de D. aurita, use as contagens por sexo e status para calcular o total de indivíduos, o total positivo e a fração positiva nesse subconjunto. Não chame essa fração de prevalência de toda a Mata Atlântica.

**Resposta de referência:** O total é 131 + 133 + 123 + 75 = 462; os positivos são 198. A fração é 42,86% nesse subconjunto, não uma estimativa automaticamente representativa de todo o bioma.

**Itens avaliados:**
- Negativos: 131 fêmeas e 133 machos; positivos: 123 fêmeas e 75 machos
- Total 462 e total positivo 198
- 198/462 ≈ 42,86%; tolerância 0,1 ponto percentual
- Fração apenas do subconjunto da tabela

**Erros críticos:**
- Usar a base de 3.000 como denominador
- Generalizar a fração para todo o bioma

**Evidências:** (ecology.030 OR ecology.031)

## R21 — interpretacao_cientifica

Que relação entre biodiversidade e infecção o estudo de D. aurita descreve e como ela se conecta à hipótese do efeito de diluição? Por que isso não autoriza afirmar uma lei causal universal?

**Resposta de referência:** O estudo relata menores taxas em áreas mais diversas, em consonância com o efeito de diluição. A hipótese relaciona diversidade à redução da transmissão; esses resultados não estabelecem causalidade universal para qualquer ambiente ou parasito.

**Itens avaliados:**
- Maior diversidade associada a menores taxas de infecção no relato do estudo
- Hipótese de diluição: diversidade pode reduzir transmissão/interação com hospedeiros competentes
- Associação e hipótese não equivalem a causalidade universal comprovada

**Erros críticos:**
- Dizer que biodiversidade elimina toda transmissão
- Afirmar ensaio causal controlado não descrito

**Evidências:** (ecology.abstract) AND (ecology.007)

## R22 — metodologia_qualitativa

Na pesquisa sobre Aprendizagem Tecnológica Ativa no IFAM Manacapuru, quem participou, quais instrumentos foram usados e qual foi a abordagem de pesquisa? Evite descrevê-la como um experimento randomizado.

**Resposta de referência:** O estudo qualitativo, documental e de campo no EMI em Administração do IFAM Manacapuru usa questionários com 20 estudantes e entrevistas semiestruturadas com sete docentes. Não é descrito como ensaio randomizado.

**Itens avaliados:**
- 20 estudantes em questionários
- 7 docentes em entrevistas semiestruturadas
- Abordagem qualitativa, pesquisa documental articulada à de campo
- Contexto do Ensino Médio Integrado em Administração do IFAM Manacapuru

**Erros críticos:**
- Trocar as contagens entre docentes e estudantes
- Inventar grupo de controle randomizado

**Evidências:** (ata.002)

## R23 — achado_e_produto

A pesquisa de ATA concluiu que os docentes não usavam tecnologias digitais? Qual lacuna identificou e o que o produto educacional oferece para enfrentá-la?

**Resposta de referência:** Não: os docentes já as utilizavam, mas faltava sistematização teórica. O produto reúne teoria, atividades, exemplos de aplicação e sugestões de avaliação formativa e diagnóstica.

**Itens avaliados:**
- Docentes já incorporavam metodologias ativas e tecnologias digitais
- Lacuna de sistematização teórica das práticas
- Material com aporte teórico, atividades práticas e exemplos de TDICs/metodologias ativas
- Sugestões de avaliação formativa e diagnóstica

**Erros críticos:**
- Atribuir a lacuna à ausência total de uso de tecnologia
- Inventar melhoria numérica em notas escolares

**Evidências:** (ata.002)

## R24 — comparacao_multidocumental

Compare DustAI e o sistema de VFC/COVID-19 como sistemas de sensoriamento com processamento remoto: variável observada, comunicação/interface explicitada e tarefa do modelo. Não suponha que ambos usam LoRaWAN.

**Resposta de referência:** DustAI calibra medições de partículas, transmitidas por LoRaWAN, com AM na nuvem. A tese de COVID usa VFC de oxímetro enviada a servidor remoto e monitoramento web para investigar estados de saúde. Não há base nesses trechos para transferir LoRaWAN ao segundo projeto.

**Itens avaliados:**
- DustAI mede material particulado e faz calibração com AM na nuvem
- DustAI explicita LoRaWAN
- VFC/COVID usa VFC coletada por oxímetro, servidor remoto e monitoramento web
- VFC/COVID classifica/investiga estados associados à COVID; LoRaWAN não está demonstrado nessas evidências para esse sistema

**Erros críticos:**
- Transferir tecnologia ou métrica de um estudo ao outro
- Tratar a calibração de partículas como diagnóstico médico

**Evidências:** (dust.000) AND (covid.000 OR covid.001)

## R25 — comparacao_multidocumental

Compare o papel da personalização em PersonaReAct e no sistema de nutrição oncológica. O que é adaptado, quais informações orientam a adaptação e por que não são a mesma técnica?

**Resposta de referência:** PersonaReAct personaliza a apresentação da resposta por perfil usando Tailor. A nutrição personaliza recomendações sob metas e restrições, com TOPSIS/NSGA-II e perfis sintéticos. Compartilham a intenção de adaptar ao usuário, não a mesma técnica.

**Itens avaliados:**
- PersonaReAct adapta a resposta final ao perfil funcional via Tailor
- Nutrição gera recomendações alimentares conforme perfis sintéticos, metas e restrições
- TOPSIS/NSGA-II não são o módulo Tailor
- Personalização linguística/comunicativa e recomendação multicritério são mecanismos distintos

**Erros críticos:**
- Dizer que o sistema nutricional foi implementado com PersonaReAct
- Confundir perfis de usuário com treinamento dos pesos

**Evidências:** (persona.002) AND (nutrition.000 OR nutrition.041)

## R26 — comparacao_multidocumental

Compare as validações do SAAL e da pesquisa ATA: quem foi consultado, por quais instrumentos e o que cada estudo procura avaliar. Essas validações medem acurácia de classificador?

**Resposta de referência:** SAAL consulta especialistas para validar um catálogo de segurança; ATA consulta estudantes e docentes sobre o processo pedagógico. Ambos usam instrumentos humanos, mas com objetivos distintos, não avaliação de acurácia preditiva.

**Itens avaliados:**
- SAAL: especialistas/engenheiros/desenvolvedores; entrevistas e questionários para validar catálogo de segurança
- ATA: questionários a 20 estudantes e entrevistas a sete docentes para investigar prática e contribuições pedagógicas
- Objetos e públicos de avaliação diferentes
- Não apresentar como métricas de acurácia de classificador

**Erros críticos:**
- Atribuir 20 estudantes e sete docentes ao SAAL
- Inventar F1 ou acurácia para esses estudos

**Evidências:** (saal.abstract) AND (ata.002)

## R27 — comparacao_multidocumental

DustAI e a dissertação sobre ações usam Pearson e métricas de erro. Compare a finalidade dessas métricas nos dois estudos e explique por que seus valores não devem ser usados para declarar qual projeto é 'melhor' globalmente.

**Resposta de referência:** No DustAI, as métricas avaliam calibração de partículas; nas ações, previsão de preços. MSE não é RMSE, e alvos e escalas diferem. Pearson e erros não permitem um ranking global direto entre projetos.

**Itens avaliados:**
- DustAI avalia calibração de sensores frente a referência, com Pearson/MAE/MSE
- Ações avalia predição de preços, com Pearson/MAE/RMSE
- Alvos, escalas, unidades, conjuntos e desenhos distintos
- Não ranquear qualidade global pela comparação direta dos números

**Erros críticos:**
- Comparar MAE de poluição com RMSE de ações como mesma escala
- Concluir que correlação maior valida causalidade

**Evidências:** (dust.001) AND (stocks.001 OR stocks.040)

## R28 — informacao_nao_demonstrada

Com base no experimento de VFC/COVID-19, qual é o desempenho garantido para um paciente novo em 2026, independentemente de histórico de infecção, dispositivo e população? Se os resultados não sustentam esse número, explique o limite sem deixar de relatar o que foi medido.

**Resposta de referência:** Não é possível fornecer essa garantia. O resumo relata 77% e 96,7% sob condições distintas; isso não demonstra desempenho independente de população, dispositivo e histórico para um paciente novo.

**Itens avaliados:**
- Não há desempenho universal garantido demonstrado
- 77% geral e 96,7% condicionado à informação de infecção recente são resultados relatados
- Não extrapolar automaticamente para novos dispositivos/populações/2026

**Erros críticos:**
- Garantir 96,7% para qualquer paciente
- Inventar validação prospectiva em 2026

**Evidências:** (covid.000 OR covid.001)

## R29 — informacao_nao_demonstrada

Qual retorno líquido anual garantido, após taxas e custos, obterei em 2026 ao usar o melhor modelo da dissertação de ações brasileiras? Diferencie o que o estudo mede da quantidade solicitada.

**Resposta de referência:** Não há retorno garantido derivável. MAE, RMSE e Pearson avaliam predição no experimento; não constituem demonstração de lucro líquido futuro após taxas e custos.

**Itens avaliados:**
- Não é possível obter retorno líquido anual garantido desses resultados
- Estudo relata erros de predição e correlação, não garantia de lucro
- Métricas históricas não determinam desempenho de investimento em 2026 após custos

**Erros críticos:**
- Converter Pearson 0,9998 em retorno de 99,98%
- Inventar backtest com custos ou promessa de lucro

**Evidências:** (stocks.001) AND (stocks.040)

## R30 — contradicao_documental

No PersonaReAct, é inequívoco qual modelo julgou as respostas? Compare a apresentação de E1 com a passagem sobre a análise automática: reproduza as duas designações e diga o que falta para afirmar qual avaliador foi realmente executado.

**Resposta de referência:** Não é inequívoco nesses trechos: a visão de E1 cita GPT-4o; a descrição da análise cita 4o-mini. A configuração ou os registros do experimento precisam ser verificados antes de afirmar qual foi executado.

**Itens avaliados:**
- Apresentação de E1 menciona G-Eval com GPT-4o como base
- Passagem de análise automática menciona 4o-mini da OpenAI como julgador
- Reconhecer ambiguidade/divergência textual
- É necessário verificar configuração, código ou registros de execução para resolver, sem escolher por tamanho do modelo

**Erros críticos:**
- Tratar GPT-4o e 4o-mini como nomes idênticos
- Resolver a ambiguidade sem evidência adicional

**Evidências:** (persona.050) AND (persona.053)

## Registro das fontes

- **ecology**: Explorando a interseção entre paisagem, biodiversidade e infecção por Trypanosoma cruzi em ambientes fragmentados da Mata Atlântica: uma análise com uso de aprendizado de máquina — `CRUZ_05d756b9b877ca76d077ba6eb52d9a31` — https://arca.fiocruz.br/handle/icict/74594
- **ata**: Aprendizagem Tecnológica Ativa (ATA): um elo de dialogicidade para a formação humana integral no ensino médio integrado — `IFAM-1_7008292e03badb1093e70eecaa3bd37c` — http://repositorio.ifam.edu.br/jspui/handle/4321/1739
- **stocks**: Aplicação de Estratégias Híbridas de Aprendizado Profundo na Estimação de Preços no Mercado de Ações Brasileiro — `UNIOESTE-1_25eeffbb8503efe67a07db1336ce2e2c` — https://tede.unioeste.br/handle/tede/7816
- **nutrition**: Um Sistema de Recomendação para Nutrição Oncológica baseado em Decisão Multicritério — `UNIOESTE-1_5d299244327e069878702d38bd3ed462` — https://tede.unioeste.br/handle/tede/7924
- **covid**: Aprendizado de máquina e dispositivo vestível na identificação dos diferentes estágios da COVID-19 utilizando a variabilidade da frequência cardíaca. — `csv_07b66c97bdaa48f82a2354b0f340d1b9185183a45c00d2c5b8c104381281a68b` — http://bibliotecatede.uninove.br/handle/tede/3505
- **dust**: DustAI: Monitor de Material Particulado de Baixo Custo com Calibração via Aprendizado de Máquina — `csv_09029e92e5a17b06f0a70b1699ed875bd01cabe463405ad8a7d9ca86c7fbdec8` — https://tede.unioeste.br/handle/tede/7102
- **persona**: PersonaReAct: personalização de respostas em modelos de linguagem com base no Paradigma ReAct — `csv_09f387404ed4a4f564207ec7beb30046d692dbd5edd08d79527c0cc7f783c39a` — http://repositorio.ufc.br/handle/riufc/82398
- **saal**: SAAL: catálogo do requisito não funcional de segurança para ambientes de vida assistida — `csv_0bb74d9720951c01683741d6157c9acae3c4052873d0956395888a6d1965a094` — http://repositorio.ufc.br/handle/riufc/80542
