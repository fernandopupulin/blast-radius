# Blast Radius v4

A v4 usa cobertura por função, acesso a fixtures e balanceamento de 0 a 8 workers. Para uma troca isolada de inteiro em um atributo de classe de dialeto, usa o mapa de leituras observadas desse atributo no SQLGlot e nos testes. Algumas alterações isoladas em configurações de classes também podem usar o mapa de construção e referências dessas classes.

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

Em prática, a v3 registrou 539,987 s de seleção e um miss, que acrescentou 300 s na simulação. A v4 mantém a cobertura da função mesmo para condições simples, e sua pontuação oficial ainda precisa ser medida.

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
PYTHON_CPU_COUNT=4 SKIP_INTEGRATION=0 PYTHONPATH=/profile:/src python /profile/profile_classes.py
python /profile/build_class_map.py /profile/attributes.json.gz /profile/results /profile/final.json.gz
```

Copie `/profile/final.json.gz` para a raiz com o nome `impact.json.gz`. Os geradores usam o checkout e as observações do commit fixado. Use uma pasta `/profile/results` vazia para cada coleta.

Em uma segunda validação independente, alterei `BigQuery.WEEK_OFFSET` de −1 para 0 e rodei a suíte completa. Dez subtestes falharam dentro de `tests/test_optimizer.py::TestOptimizer::test_simplify`, que vale como um teste no scorer. A v3 incluiu esse teste entre os 10 que selecionou.
