# Direction B-2: Genetic Algorithm (GA) for Thermal-Aware Task Mapping.
#
# Modules:
#   ga_mapper  — GAMapper class, GAConfig, evaluate_fitness()
#   run        — CLI entry point (mirrors B-1/run.py)
#
# Cost function: NormalizedCostModel.total_cost() + optional peak-temp penalty.
# Same objective as B-1, different optimization algorithm (GA vs greedy).
#
# Note: this directory is named "B-2" (with hyphen), so it cannot be imported
# as a Python package.  Import ga_mapper by adding this directory to sys.path:
#     sys.path.insert(0, ".../Experiment/B-2")
#     from ga_mapper import GAMapper, GAConfig
