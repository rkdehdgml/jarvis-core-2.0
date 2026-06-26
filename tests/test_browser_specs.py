"""browser_specs 검증: registry.py에 아직 등록 전이므로 로컬에서 직접 register.

실행: python -m tests.test_browser_specs
"""
from commands.registry import register, COMMAND_MAP
from commands.specs import browser_specs


def main() -> None:
    if "BROWSER_OPEN_URL" not in COMMAND_MAP:
        register(browser_specs.SPECS)

    spec = COMMAND_MAP["BROWSER_OPEN_URL"]
    assert spec.bridge == "exe", "bridge는 exe여야 한다(PowerShell 인젝션 회피)"
    assert spec.binary == "explorer.exe", "binary는 explorer.exe여야 한다"
    assert spec.build_args({"url": "https://example.com"}) == ["https://example.com"]

    print("test_browser_specs 통과")


if __name__ == "__main__":
    main()
