# HNOCS Experiment Runbook

本文档记录 B-2 实验在本地电脑和实验室主机上的已验证路径、环境设置和运行命令。运行前先确认路径，不要混用 `D:\HNOCS` 和 `E:\mzj\HNOCS_mzj`。

## 1. 机器与路径

### 本地电脑

| 项 | 值 |
|---|---|
| HNOCS workspace | `D:\HNOCS` |
| Python | `Python 3.13.5` |
| Python executable | `D:\anaconda3\python.exe` |
| OMNeT++ root | `D:\omnetpp\omnetpp-6.3.0` |
| HNOCS executable | `D:\HNOCS\libhnocs.exe` |
| B-2 script | `D:\HNOCS\experiment\B-2\run.py` |
| OMNeT++ ini | `D:\HNOCS\examples\task_driven\omnetpp.ini` |
| NED paths | `D:\HNOCS\src;D:\HNOCS\examples\task_driven` |

PowerShell setup:

```powershell
$env:OMNETPP_ROOT = "D:\omnetpp\omnetpp-6.3.0"
$env:PATH = "D:\HNOCS;D:\omnetpp\omnetpp-6.3.0\bin;D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\clang64\bin;D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\usr\bin;" + $env:PATH
cd D:\HNOCS
```

### 实验室主机

| 项 | 值 |
|---|---|
| Hostname | `DESKTOP-N2P5LH1` |
| OS | Windows 10 Pro, version 2009, 64-bit |
| CPU | AMD Ryzen 9 9950X 16-Core Processor |
| CPU cores / logical processors | 16 cores / 32 logical processors |
| RAM | about 203.6 GB |
| HNOCS workspace | `E:\mzj\HNOCS_mzj` |
| Python | `Python 3.12.10` |
| Python executable | `C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe` |
| OMNeT++ root | `S:\omnetpp-6.3.0` |
| HNOCS executable | `E:\mzj\HNOCS_mzj\libhnocs.exe` |
| B-2 script | `E:\mzj\HNOCS_mzj\experiment\B-2\run.py` |
| OMNeT++ ini | `E:\mzj\HNOCS_mzj\examples\task_driven\omnetpp.ini` |
| NED paths | `E:\mzj\HNOCS_mzj\src;E:\mzj\HNOCS_mzj\examples\task_driven` |

PowerShell setup:

```powershell
$env:OMNETPP_ROOT = "S:\omnetpp-6.3.0"
$env:PATH = "E:\mzj\HNOCS_mzj;S:\omnetpp-6.3.0\bin;S:\omnetpp-6.3.0\tools\win32.x86_64\clang64\bin;S:\omnetpp-6.3.0\tools\win32.x86_64\usr\bin;" + $env:PATH
cd E:\mzj\HNOCS_mzj
```

## 2. 环境检查

每次换机器或新开 PowerShell 后先执行：

```powershell
python --version
where.exe python
python -c "import sys; print(sys.executable)"
opp_run --version
opp_scavetool
```

检查关键文件：

```powershell
# 本地电脑
Test-Path D:\HNOCS\libhnocs.exe
Test-Path D:\HNOCS\examples\task_driven\omnetpp.ini
Test-Path D:\omnetpp\omnetpp-6.3.0\bin\opp_scavetool.exe

# 实验室主机
Test-Path E:\mzj\HNOCS_mzj\libhnocs.exe
Test-Path E:\mzj\HNOCS_mzj\examples\task_driven\omnetpp.ini
Test-Path S:\omnetpp-6.3.0\bin\opp_scavetool.exe
```

`opp_run --version` 在非工程目录下可能继续打印 `Missing configuration`，只要版本号能打印出来即可。`opp_scavetool --version` 不可用，直接执行 `opp_scavetool` 能显示帮助信息即可。

## 3. 已验证实验命令

### 本地电脑：B-2-v2，30 generations

以下命令已成功运行，用于生成 `out\B-2-v2`：

```powershell
$env:OMNETPP_ROOT = "D:\omnetpp\omnetpp-6.3.0"
$env:PATH = "D:\HNOCS;D:\omnetpp\omnetpp-6.3.0\bin;D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\clang64\bin;D:\omnetpp\omnetpp-6.3.0\tools\win32.x86_64\usr\bin;" + $env:PATH

cd D:\HNOCS
python experiment\B-2\run.py --all --workers 8 --generations 30 --population 50 --seed 42 -o out\B-2-v2
```

参数：`seed=42`，`population=50`，`generations=30`，`workers=8`，`omnet-timeout` 使用默认值。该目录仍可能包含 Optic 历史结果，但当前论文不使用 Optic。

### 实验室主机：B-2-v3-g60，60 generations

以下命令已在实验室主机成功运行，用于生成 `out\B-2-v3-g60`：

```powershell
$env:OMNETPP_ROOT = "S:\omnetpp-6.3.0"
$env:PATH = "E:\mzj\HNOCS_mzj;S:\omnetpp-6.3.0\bin;S:\omnetpp-6.3.0\tools\win32.x86_64\clang64\bin;S:\omnetpp-6.3.0\tools\win32.x86_64\usr\bin;" + $env:PATH

cd E:\mzj\HNOCS_mzj
python experiment\B-2\run.py `
  --all `
  --workers 8 `
  --generations 60 `
  --population 50 `
  --seed 42 `
  --omnet-timeout 300 `
  -o out\B-2-v3-g60 `
  --omnet-bin "E:\mzj\HNOCS_mzj\libhnocs.exe" `
  --omnet-ned-paths "E:\mzj\HNOCS_mzj\src;E:\mzj\HNOCS_mzj\examples\task_driven" `
  --omnet-workdir "E:\mzj\HNOCS_mzj\examples\task_driven" `
  --omnet-ini "E:\mzj\HNOCS_mzj\examples\task_driven\omnetpp.ini" `
  --omnetpp-root "S:\omnetpp-6.3.0"
```

参数：`seed=42`，`population=50`，`generations=60`，`workers=8`，`omnet-timeout=300s`。这是当前长代数实验的主机已验证命令。

## 4. Dry Run 和进度显示

确认实验计划，不启动 OMNeT++：

```powershell
python experiment\B-2\run.py --all --credibility --dry-run -o out\B-2-credibility
```

终端进度显示使用 `--verbose`。它会打印 baseline、每代 `Gen` 进度、OMNeT++ config 名称和 timeout 信息。例如：

```powershell
python experiment\B-2\run.py `
  --csv examples\task_driven\static\tasks_gemm_static.csv `
  --workers 4 `
  --generations 5 `
  --population 12 `
  --seed 42 `
  --verbose `
  -o out\smoke-gemm
```

如果在实验室主机上运行 smoke test，请显式传入 `--omnet-bin`、`--omnet-ned-paths`、`--omnet-workdir`、`--omnet-ini`、`--omnetpp-root`，不要依赖默认的 `D:\HNOCS` 路径。

## 5. 输出文件和结果检查

单次输出目录：

```text
out\<run-name>\<benchmark>\
```

每个 benchmark 应包含：

- `metrics.json`
- `history.json`
- `remapped.csv`
- `summary.txt`

多 seed / credibility 输出还会生成：

- `runs_summary.csv`
- `aggregate_summary.csv`
- `aggregate_summary.json`

结果有效性最低检查：

```powershell
Get-Content out\<run-name>\<benchmark>\summary.txt
Get-Content out\<run-name>\<benchmark>\metrics.json
Get-Content out\<run-name>\<benchmark>\history.json
```

以下结果必须视为无效，不能用于论文：

- `T_max -> -273.1C`
- `makespan 0.0us`
- `E_total 0.000mJ`
- `history.json` 每代都是 `best_fitness: Infinity`

出现无效结果时，优先检查路径参数是否仍指向旧机器路径，尤其是实验室主机不能使用 `D:\HNOCS` 默认路径。
