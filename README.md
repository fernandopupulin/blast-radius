# Blast Radius v3

A v3 usa a cobertura por função, o acesso a fixtures e o balanceamento de 0 a 8 workers da v2. Em condições simples de uma linha, usa a cobertura da linha quando há dados. Para uma troca isolada de inteiro em um atributo de classe de dialeto, usa o mapa de leituras observadas desse atributo no SQLGlot e nos testes.

O mapa reúne os testes que passaram por qualquer leitura Python observada, inclusive em código compartilhado. A geração descarta nomes com acesso literal indireto, importação, referências sem cobertura ou leitura durante a coleta. A regra cobre alterações simples de literais, com os demais casos encaminhados à lógica de cobertura da v2 ou à suíte inteira. A análise estática pode deixar de encontrar acessos puramente dinâmicos, por exemplo nomes construídos em tempo de execução.

## Amostra oficial

| Versão | Segundos simulados | Misses |
| --- | ---: | ---: |
| v2, cobertura por função | 304,691 | 0 |
| Híbrida, função ou condição de uma linha | 300,090 | 0 |
| v3, com mapa de atributos inteiros | 266,135 | 0 |

A v3 produziu três saídas idênticas no Docker Linux/AMD64 sob as restrições do kit. A estimativa local incluindo CPU, arredondada pela regra do scorer, foi de 267,0 s. O lote sintético de 45 patches produziu 316.620 bytes e o ensaio independente do gerador Dremio também passou.

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
python /profile/build_attribute_map.py /src /profile/packed.json.gz /profile/final.json.gz
```

Copie `/profile/final.json.gz` para a raiz com o nome `impact.json.gz`. O gerador usa o checkout e a cobertura do commit fixado.

Em uma segunda validação independente, alterei `BigQuery.WEEK_OFFSET` de −1 para 0 e rodei a suíte completa. Dez subtestes falharam dentro de `tests/test_optimizer.py::TestOptimizer::test_simplify`, que vale como um teste no scorer. A v3 incluiu esse teste entre os 10 que selecionou.
