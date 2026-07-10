Com base em tudo o que refinamos, o desenvolvimento está estruturado em 12 sprints,
separando claramente descoberta, arquitetura, implementação e validação.
 
Sprint      Objetivo                          Principais Entregáveis
 
0A          Descoberta e Produto              Visão do projeto, missão, personas, casos de uso,
                                               requisitos funcionais e não funcionais, critérios
                                               de sucesso, escopo, roadmap inicial.
 
0B          Arquitetura da Solução            Stack tecnológica, diagramas (alto nível),
                                               arquitetura medalhão, estrutura de diretórios,
                                               convenções, ADRs iniciais, PROJECT_CONTEXT.md v1.
 
1           Modelagem de Dados                Modelo dimensional (Star Schema), dicionário de
                                               dados, contratos de interface, modelo ER, tabelas
                                               Bronze/Silver/Gold, estratégia de watermark e
                                               versionamento.
 
2           Pipeline Bronze                   Extração das APIs e bases públicas, ingestão
                                               incremental, persistência em Parquet, metadados
                                               de ingestão, logging, tratamento de erros.
 
3           Pipeline Silver                   Limpeza, padronização, enriquecimento, validações
                                               com Pandera, deduplicação, Data Quality Report,
                                               carga no DuckDB.
 
4           Camada Gold                       Construção do Data Warehouse analítico, fatos,
                                               dimensões, métricas semânticas, tabelas
                                               analíticas e indicadores consolidados.
 
5           Analytics e IA                    Estatística, correlações, detecção de anomalias,
                                               clusterização, análise de redes com NetworkX,
                                               cálculo de scores e geração das tabelas analíticas.
 
6           API                               Desenvolvimento da FastAPI, contratos REST,
                                               documentação OpenAPI/Swagger, paginação, filtros,
                                               testes da API e endpoints para consumo por
                                               dashboards e agentes de IA (agent-ready).
 
6.5         Validação End-to-End              Execução completa com dados reais, validação do
                                               pipeline, ajustes de performance, revisão da
                                               qualidade dos dados e atualização do
                                               PROJECT_CONTEXT.md.
 
7           Dashboard                         Desenvolvimento do Streamlit, páginas analíticas,
                                               filtros, mapas, grafos, visualizações interativas,
                                               exportações (CSV, Excel e PDF) e experiência
                                               do usuário.
 
8           Testes                            Testes unitários, de integração, de pipeline e de
                                               API. Cobertura mínima de 80% com Pytest. Revisão
                                               de contratos de dados e validações.
 
9           Deploy + Documentação             Docker, Docker Compose, GitHub Actions (CI/CD com
                                               execução diária), README completo, guias de
                                               instalação, deploy e operação, documentação final.
 
 
Artefatos que acompanham todas as sprints
 
Cada sprint deve terminar com a atualização dos seguintes documentos:
 
PROJECT_CONTEXT.md (contexto consolidado do projeto)
ADR.md (Architecture Decision Records)
BACKLOG.md (itens concluídos e pendentes)
CHANGELOG.md (histórico das alterações)
Diagramas atualizados, quando houver mudanças arquiteturais
 
 
Fluxo de trabalho sugerido
 
Para cada sprint, siga sempre o mesmo ciclo:
 
1. Ler o PROJECT_CONTEXT.md.
2. Validar os contratos de interface e ADRs existentes.
3. Implementar apenas o escopo da sprint.
4. Atualizar documentação e contexto.
5. Realizar revisão técnica.
6. Obter aprovação antes de iniciar a próxima sprint.