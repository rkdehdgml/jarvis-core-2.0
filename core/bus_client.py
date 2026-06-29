"""대전광역시 버스 도착정보 API 클라이언트.

엔드포인트: https://apis.data.go.kr/6300000/arrive/getArrInfoByStopID
파라미터:   BusStopID (정류소 노드 ID, 예: 8001378)
"""
import logging
import os
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_ENDPOINT = "https://apis.data.go.kr/6300000/arrive/getArrInfoByStopID"
_TIMEOUT  = 10


def get_arrivals(bus_stop_id: str, service_key: str | None = None) -> list[dict]:
    """정류소 ID로 도착 예정 버스 목록을 조회한다.

    Returns:
        list of {
            route_no    : str   # 버스 번호 (예: "102")
            car_reg_no  : str   # 차량번호 — 동일 노선 여러 대 구분용
            eta_min     : int   # 도착 예정 분
            eta_sec     : int   # 도착 예정 초 (정밀도용)
            status_pos  : int   # 남은 정류장 수
            destination : str   # 종점 이름
            stop_name   : str   # 조회한 정류소 이름
            route_cd    : str   # 노선 코드
            bus_node_id : str   # 정류소 노드 ID
        }
    """
    key = service_key or os.getenv("DAEJEON_BUS_API_KEY", "")
    if not key:
        logger.warning("DAEJEON_BUS_API_KEY 환경변수가 없습니다.")
        return []

    try:
        r = requests.get(
            _ENDPOINT,
            params={"serviceKey": key, "BusStopID": bus_stop_id},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return _parse(r.text)
    except requests.RequestException as exc:
        logger.warning(f"버스 API 호출 실패: {exc}")
        return []


def _parse(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning(f"버스 API XML 파싱 오류: {exc}")
        return []

    hdr_cd = root.findtext("msgHeader/headerCd", "")
    if hdr_cd != "0":
        msg = root.findtext("msgHeader/headerMsg", "알 수 없는 오류")
        logger.warning(f"버스 API 응답 오류: {hdr_cd} — {msg}")
        return []

    items = []
    for node in root.findall("msgBody/itemList"):
        def t(tag: str) -> str:
            return (node.findtext(tag) or "").strip()

        try:
            eta_min    = int(t("EXTIME_MIN") or 999)
            eta_sec    = int(t("EXTIME_SEC") or 0)
            status_pos = int(t("STATUS_POS") or 0)
        except ValueError:
            eta_min, eta_sec, status_pos = 999, 0, 0

        items.append({
            "route_no":    t("ROUTE_NO"),
            "car_reg_no":  t("CAR_REG_NO"),
            "eta_min":     eta_min,
            "eta_sec":     eta_sec,
            "status_pos":  status_pos,
            "destination": t("DESTINATION"),
            "stop_name":   t("STOP_NAME"),
            "route_cd":    t("ROUTE_CD"),
            "bus_node_id": t("BUS_NODE_ID"),
        })

    return sorted(items, key=lambda x: x["eta_min"])
