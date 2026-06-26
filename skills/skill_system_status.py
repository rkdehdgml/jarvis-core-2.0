"""skills/skill_system_status.py — Windows 호스트의 종합 상태(CPU/메모리/디스크) 조회.

skill_system_info(psutil 기반 단일 지표 빠른 조회)와 역할이 분리된 스킬이다.
이쪽은 PowerShell Get-CimInstance로 CPU/메모리/디스크를 한 번에 받아오는 종합 조회용이라
트리거에 "CPU"/"메모리"/"배터리"를 의도적으로 쓰지 않는다(라우팅 충돌 방지).
"""
import json

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command


class SystemStatusSkill(Skill):
    """Windows 호스트의 CPU/메모리/디스크 상태를 종합 조회한다."""

    name = "system_status"
    description = "Windows 호스트의 CPU/메모리/디스크 상태를 종합 조회한다"
    triggers = [
        "시스템 상태",
        "컴퓨터 상태",
        "디스크 용량",
        "디스크 사용량",
        "저장공간",
        "하드 용량",
        "드라이브 용량",
    ]
    examples = ["시스템 상태 알려줘", "디스크 용량 얼마나 남았어", "컴퓨터 상태 어때"]

    def can_handle(self, intent: str, text: str) -> float:
        for trigger in self.triggers:
            if trigger in text:
                return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        result = run_command("SYSTEM_STATUS_QUERY")
        if not result.ok:
            return SkillResult(speech="시스템 상태를 조회하지 못했습니다.", success=False)

        try:
            parsed = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return SkillResult(speech="시스템 상태를 조회하지 못했습니다.", success=False)

        cpu_load = parsed.get("cpu_load")
        mem_total = parsed.get("mem_total_mb")
        mem_free = parsed.get("mem_free_mb")
        disk_total = parsed.get("disk_total_gb")
        disk_free = parsed.get("disk_free_gb")

        # LoadPercentage는 단일 샘플에서 가끔 null로 온다 — 그 경우 사용률 문구만 생략한다.
        if cpu_load is None:
            cpu_part = "CPU 사용률은 확인할 수 없었고, "
        else:
            cpu_part = f"CPU 사용률은 {cpu_load}%이고, "

        mem_used = mem_total - mem_free
        speech = (
            f"{cpu_part}"
            f"메모리는 전체 {mem_total}MB 중 {mem_used}MB 사용 중입니다. "
            f"C 드라이브는 전체 {disk_total}GB 중 {disk_free}GB 남았습니다."
        )

        return SkillResult(speech=speech, success=True, data=parsed)
