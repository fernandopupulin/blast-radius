# Blast Radius v11

A v6 acompanha também os testes que leem os atributos de classe nos quais `setUpClass` armazena pares de SQL. Quando a mudança preserva a estrutura e os metadados que o carregador usa, seleciona esses consumidores e os leitores diretos. Uma mudança que possa afetar a preparação mantém a cobertura compartilhada de toda a classe.

Para Python, uma troca isolada de uma expressão executável em uma linha pode usar a cobertura da linha depois que a AST confirma que o restante do arquivo é equivalente. Mutações com efeito mais amplo mantêm a cobertura da função. O mapa de leituras de atributos escalares cobre inteiros e booleanos de dialetos, parsers e geradores, com verificação de tipo e inicialização.

A v7 amplia a substituição de literais para configurações com strings, listas, tuplas e dicionários de estrutura preservada. Quando possível, atribui a leitura ao dono efetivo da configuração na hierarquia, mantendo leituras não atribuídas e dependências de preparação compartilhada. Também trata valores padrão literais de funções e mudanças isoladas de tipo de retorno da metadata de expressões. O recorte usa apenas observações da suíte no commit fixado.

A v8 experimental também seleciona leitores de constantes locais de módulo quando o valor literal conserva a estrutura e todos os leitores mapeados estão em funções. Importações, acessos externos ou inicialização observada impedem esse recorte. Em arquivos de teste, uma troca isolada da constante esperada no último `self.assertEqual` de um teste preserva os testes que executam seu corpo.

O perfil de comparações registra apenas os tipos dos operandos que a suíte original executou. Para uma alteração isolada entre identidade e igualdade, com todos os demais nós da AST preservados, esses domínios permitem remover testes de execução normal quando os operadores têm a mesma semântica. São aceitos casos de igualdade padrão de objetos, booleanos canônicos e membros registrados de uma mesma enumeração textual com igualdade nativa. A seleção mantém os leitores diretos do fonte e subprocessos. Domínios mistos sem garantia seguem a cobertura normal.

A v9 também registra os valores booleanos que os operandos de condições assumiram em cada teste. Para uma mudança isolada de operadores booleanos, compara o resultado e a ordem de avaliação dos operandos sob todas as combinações compatíveis com esse perfil. Uma avaliação ausente é tratada como desconhecida. Para comparações entre tipos primitivos exatos, registra as relações de ordem observadas e mantém todos os testes em que a troca de operador possa alterar o resultado. A cobertura inclui as tarefas dos processos filhos. A coleta descarta o recorte por teste quando o mesmo ponto executa fora do corpo de um teste em Python.

A cobertura dos interpretadores iniciados por subprocessos separa os arquivos que a execução importou dos que ficaram fora dela. Mudanças em inicialização ou configuração dos arquivos importados continuam a incluir o teste. A leitura direta de arquivos usa o mapa de dependências observado.

A última versão rastreia o consumo das entradas de despacho de SHOW e de escapes numéricos, inclusive quando a tabela de despacho é copiada para uma subclasse. Uma edição isolada precisa preservar as chaves e corresponder à estrutura de uma configuração conhecida. Para argumentos padrão imutáveis, a coleta identifica chamadas que sempre receberam um valor distinto do padrão original.

Uma edição isolada de expressão pode usar sua cobertura durante a execução mesmo quando a função que a contém também é chamada durante a coleta. O seletor exige que as linhas da expressão tenham cobertura atribuída ou permaneçam sem execução, que a coleta não execute a expressão e que a compilação preserve a estrutura dos escopos léxicos. Mudanças fora dessas condições seguem a seleção conservadora.

O mapa reúne os testes que passaram por qualquer leitura Python observada, inclusive em código compartilhado. A geração descarta nomes com acesso literal indireto, importação, referências sem cobertura ou leitura durante a coleta. A regra cobre alterações simples de literais, com os demais casos encaminhados à lógica de cobertura da v2 ou à suíte inteira. A análise estática pode deixar de encontrar acessos puramente dinâmicos, por exemplo nomes construídos em tempo de execução.

A coleta adicional registra as classes usadas por cada teste, incluindo suas superclasses e as tarefas executadas em processos filhos. O seletor usa esse mapa apenas para alterações de um valor que preservam a estrutura da configuração validada. Adiciona referências observadas à classe e inclui testes que iniciam subprocessos comuns. Referências que só usam a identidade da classe como chave de dicionário ou anotação ficam fora desse mapa complementar.

## Amostra oficial

| Versão | Segundos simulados | Misses |
| --- | ---: | ---: |
| v2, cobertura por função | 304,691 | 0 |
| Híbrida, função ou condição de uma linha | 300,090 | 0 |
| v3, com mapa de atributos inteiros | 266,135 | 0 |
| v4, primeira variante com mapa de classes | 197,589 | 0 |
| v4, mapa de classes sem referências de identidade | 174,581 | 0 |
| v5, dependências de leitura e preparação compartilhada | 186,307 | 0 |
| v6, configurações escalares e consumidores de fixtures | 180,484 | 0 |
| v7, donos de atributos, padrões de funções e metadata | 180,484 | 0 |
| v8 experimental, constantes locais e asserções finais | 180,484 | 0 |
| v8, equivalência de comparações pelos tipos observados | 134,611 | 0 |
| v9, condições por teste e cobertura de subprocessos | 117,803 | 0 |
| v10 experimental, entradas de tabelas e argumentos padrão | 106,505 | 0 |
| v11, cobertura de expressões e escopos léxicos | 104,474 | 0 |

Em prática, a v5 registrou 559,384 s simulados e zero misses, com 560,7 s oficiais. A v4 registrou 528,624 s de seleção e um miss, para 829,9 s oficiais.

A v6 marcou 549,0 s oficiais, com 547,613 s simulados, 1,42 s de CPU mediana e zero misses.

A v7 marcou 549,2 s oficiais, com os mesmos 547,613 s simulados, CPU mediana de 1,55 s e zero misses.

Uma mutação independente de fixture compartilhada pelo executor e pelo otimizador reproduziu uma falha omitida pela v4. A v5 recuperou essa falha e incluiu todas as demais falhas registradas pela suíte completa para essa mutação.

Nas 12 mutações independentes com falhas confirmadas, v5 e v6 cobriram todas as falhas. O custo total simulado caiu de 154,817 s para 71,522 s. Na mutação que usa preparação compartilhada, caiu de 25,454 s para 8,901 s. Mudanças com metadados inválidos ainda acionam a seleção compartilhada.

Nas 17 mutações independentes verificadas nesta rodada, v6 e v7 cobriram todas as falhas. O custo simulado total caiu de 255,607 s para 146,326 s. Três mutações com configuração de forma inválida, tipo desconhecido e valor padrão dinâmico mantiveram a suíte inteira.

A v8 experimental cobriu todas as falhas conhecidas em 20 mutações independentes. O custo combinado das três novas mutações caiu de 110,451 s para 11,670 s. A alteração de uma asserção anterior e a introdução de uma chamada na inicialização continuaram a selecionar a suíte inteira.

A v8 validada com Docker Linux/AMD64 cobriu todas as falhas confirmadas em 21 mutações independentes. O custo simulado combinado caiu de 259,741 s na v7 para 160,960 s. A troca de igualdade por identidade em uma comparação de datas preservou a seleção do teste que falhava.

A v9 cobriu as mesmas 21 mutações com 156,407 s simulados de custo combinado e zero misses. No kit, cinco mudanças prescindiram de workers, graças à equivalência de comparações e à cobertura do interpretador isolado.

Mais nove mutações foram executadas com a suíte completa. A v9 cobriu todas as falhas e reduziu o custo desse grupo de 194,827 s na v8 para 188,970 s. Nas trocas comportamentalmente equivalentes de condição e limite trimestral, selecionou zero workers. Uma importação antecipada de dialeto ainda selecionou o teste do interpretador isolado que falhou.

A v11 cobriu todas as falhas verificadas nas 30 mutações. O custo combinado caiu de 345,377 s na v9 para 270,965 s. No caso de despacho MySQL, o custo caiu de 25,454 s para 2,018 s. A mudança no limite de nós do parser manteve o teste que falhou e custou 30,819 s.

## Executar com o kit

Copie `Dockerfile`, `selector.py`, `impact.json.gz` e `LICENSE-SQLGLOT` para a raiz do kit oficial e execute `make sample`. Deixe esses arquivos na raiz do repositório da submissão.

## Regerar o mapa

Monte o checkout do SQLGlot fixado em `eb11aec4be8cb2122afe713a4816662c3f0fb2fa` como `/src` e uma cópia gravável de `profiling/` como `/profile`. Use a imagem criada por `docker build -t blast-radius-profiler profiling`. Execute em Linux/AMD64 a partir de `/src`, com `/profile/children` vazio.

```sh
mkdir -p /profile/children
PYTHON_CPU_COUNT=4 SKIP_INTEGRATION=0 PYTHONPATH=/profile:/src python /profile/profile_suite.py
SKIP_INTEGRATION=0 PYTHONPATH=/src COVERAGE_FILE=/profile/collection.coverage \
  python -m coverage run --source=sqlglot,tests -m pytest --collect-only -q tests
python /profile/pack_map.py
python /profile/build_attribute_map.py /src /profile/packed.json.gz /profile/attributes.json.gz
mkdir -p /profile/results
python -c 'import gzip,json; p="/profile/"; data=json.loads(gzip.open(p+"attributes.json.gz","rb").read()); json.dump(sorted(data["scalar_attribute_readers"]),open(p+"attribute-names.json","w"))'
PYTHON_CPU_COUNT=4 SKIP_INTEGRATION=0 PYTHONPATH=/profile:/src python /profile/profile_classes.py
python /profile/build_class_map.py /profile/attributes.json.gz /profile/results /profile/classes.json.gz
python /profile/build_read_map.py /profile/classes.json.gz /profile/results /profile/reads.json.gz
python /profile/build_owner_map.py /profile/reads.json.gz /profile/results /profile/owners.json.gz
python /profile/build_module_map.py /src /profile/owners.json.gz /profile/modules.json.gz
```

Para coletar comparações, mova os JSONs de `/profile/results` para uma pasta separada e recrie esse diretório vazio. Rode a mesma suíte com o observador de tipos e acrescente as observações ao mapa.

```sh
BLAST_COMPARE_DISCOVER=1 PYTHON_CPU_COUNT=4 SKIP_INTEGRATION=0 PYTHONPATH=/profile:/src python -m pytest tests -q
python /profile/build_comparison_map.py /profile/modules.json.gz /profile/results /profile/final.json.gz
```

Mantenha os perfis de `/profile/children` da coleta de cobertura. Mova os resultados anteriores e recrie `/profile/results` vazio antes de coletar condições e relações de ordem.

```sh
python /profile/build_subprocess_map.py /profile/final.json.gz /profile/children /profile/subprocess.json.gz
BLAST_BRANCH_DISCOVER=1 PYTHON_CPU_COUNT=4 SKIP_INTEGRATION=0 PYTHONPATH=/profile:/src \
  python -c 'import branch_observer; raise SystemExit(branch_observer.main())'
python /profile/build_branch_map.py /profile/subprocess.json.gz /profile/results /profile/release.json.gz
```

Copie `/profile/release.json.gz` para a raiz com o nome `impact.json.gz`. Os geradores usam o checkout e as observações do commit fixado. Use uma pasta `/profile/results` vazia para cada coleta.

Em uma segunda validação independente, alterei `BigQuery.WEEK_OFFSET` de −1 para 0 e rodei a suíte completa. Dez subtestes falharam dentro de `tests/test_optimizer.py::TestOptimizer::test_simplify`, que vale como um teste no scorer. A v3 incluiu esse teste entre os 10 que selecionou.
