#!/usr/bin/env bash
# 工具链环境修正（被 .git/hooks/pre-commit 在检查前 source）
#
# 背景：macOS 命令行工具自带的 python3（/usr/bin/python3）把字节码缓存目录
# 默认设为 ~/Library/Caches/com.apple.python。在沙箱、容器、CI 或受限权限
# 环境下该路径不可写，于是：
#   - 普通 import 会静默跳过写缓存（不报错，容易被忽略）
#   - 但 py_compile / compileall 这类显式写缓存的操作会抛
#     PermissionError: [Errno 1] Operation not permitted 并让提交直接失败
#
# 这里统一指到系统临时目录，既保证可写，也不往仓库里落缓存文件。
# 若调用方已显式设置 PYTHONPYCACHEPREFIX，则尊重其选择不覆盖。

if [ -z "${PYTHONPYCACHEPREFIX:-}" ]; then
  _qas_pycache="${TMPDIR:-/tmp}/qas-pycache"
  if mkdir -p "$_qas_pycache" 2>/dev/null && [ -w "$_qas_pycache" ]; then
    export PYTHONPYCACHEPREFIX="$_qas_pycache"
  fi
  unset _qas_pycache
fi
