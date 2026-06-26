"""commands/specs/system_specs.py — 시스템 종합 상태 조회 명령 스펙.

CPU 사용률/메모리/디스크 용량을 한 번의 Get-CimInstance PowerShell 호출로
JSON으로 받아온다. 스크립트는 매번 동일(kwargs 불필요)하므로 run_command()의
powershell 브릿지 구조와 그대로 호환된다. registry.register()로 COMMAND_MAP에 병합된다.
"""
from __future__ import annotations

from commands.registry import CommandSpec

_SCRIPT = """
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 LoadPercentage, Name
$os = Get-CimInstance Win32_OperatingSystem
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$result = [PSCustomObject]@{
    cpu_load = $cpu.LoadPercentage
    cpu_name = $cpu.Name
    mem_total_mb = [math]::Round($os.TotalVisibleMemorySize/1024)
    mem_free_mb = [math]::Round($os.FreePhysicalMemory/1024)
    disk_total_gb = [math]::Round($disk.Size/1GB,1)
    disk_free_gb = [math]::Round($disk.FreeSpace/1GB,1)
}
$result | ConvertTo-Json -Compress
""".strip()

SPECS: dict[str, CommandSpec] = {
    "SYSTEM_STATUS_QUERY": CommandSpec(
        command_id="SYSTEM_STATUS_QUERY",
        description="CPU/메모리/디스크 상태를 Get-CimInstance로 조회",
        bridge="powershell",
        script=_SCRIPT,
        timeout=15,
    ),
}
