# -*- coding: utf-8 -*-
"""
后处理模块（post_normalize）
功能：
  1) 标准化：数据集名称、时间范围、分辨率、空间位置等
  2) 合并去重：同名/别名合并；证据与变量等字段并集
  3) 业务补全：常见数据集的 institution/doi/summary 补齐
  4) 期望项补齐：如 ERA5-LAND → 逐日地表温度（衍生）
  5) 时间拆分：同一数据集多年份/多区间使用时，按需拆分为多条记录
  6) 模型产出数据自动补齐：识别“驱动/基于…得到/模拟/反演…结果/数据”
  7) 置信度融合：取最大值
  8) via-GEE 标注：若检测到 GEE 资产，补齐为 source_url（若为空）
"""

from typing import Dict, List
import regex as re
from .regex_rules import canonicalize, RE_GEE_ASSET  # 别名归一 & GEE 资产

# =========================
# 规范化工具函数
# =========================

# 时间范围规范：多种连字符统一为 "-", 只保留 YYYY 或 YYYY-YYYY
TIME_TOKEN = re.compile(r"(?:19|20)\d{2}")
TIME_RANGE = re.compile(
    r"(?P<y1>(?:19|20)\d{2})\s*(?:[—\-–~至到]|to|–)\s*(?P<y2>(?:19|20)\d{2})",
    re.I
)
TIME_SINGLE = TIME_TOKEN

# 分辨率规范：如 30 m → 30m，1 km → 1km，0.05° 保留度；也支持 日值/月值/年值
RES_CANDIDATE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>m|km|°|度|deg|米|千米|km2|km²|分钟|分|秒|min|s|h|小时|日|天|月|年|daily|monthly|yearly|day|month|year|旬值|日值|月值|年值)",
    re.I
)

# 位置规范：常见中文/英文地名统一到短词
LOC_MAP = {
    r"\bGlobal\b|全球|worldwide|全世界": "全球",
    r"\bChina\b|中国|境内|全国范围": "中国",
    r"青藏高原|Tibetan Plateau": "青藏高原",
    r"东北(地区)?|Northeast China": "中国东北",
    r"长江|Yangtze": "长江流域",
    r"黄河|Yellow\s*River": "黄河流域",
    r"\bAsia\b|亚洲": "亚洲",
    r"\bEurope\b|欧洲": "欧洲",
    r"\bAfrica\b|非洲": "非洲",
}

def _best(a, b) -> str:
    """合并策略：优先更长/信息量更多的字符串"""
    a = a or ""
    b = b or ""
    return b if len(str(b)) > len(str(a)) else a

def _dedup_list(lst: List) -> List:
    """通用去重：能 hash 的走 set，不能 hash 的转为稳定字符串键。仅用于元素为标量/字符串的列表。"""
    import json
    seen = set()
    out = []
    for x in lst or []:
        try:
            key = ("hash", hash(x))
        except TypeError:
            try:
                key = ("json", json.dumps(x, ensure_ascii=False, sort_keys=True))
            except Exception:
                key = ("repr", repr(x))
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out

def dedup_evidence(ev_list: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for e in ev_list or []:
        if not isinstance(e, dict):
            key = ("raw", str(e))
        else:
            key = (e.get("chunk_id"), e.get("start"), e.get("end"), e.get("quote"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

def normalize_time_range(text: str) -> str:
    if not text:
        return ""
    t = str(text).replace("—","-").replace("–","-").replace("~","-").replace("至","-").replace("到","-")
    m = TIME_RANGE.search(t)
    if m:
        y1, y2 = m.group("y1"), m.group("y2")
        if y1 and y2:
            return f"{y1}-{y2}"
    m2 = TIME_SINGLE.search(t)
    if m2:
        return m2.group(0)
    return t

def normalize_resolution(text: str) -> str:
    if not text:
        return ""
    t = str(text)
    m = RES_CANDIDATE.search(t)
    if not m:
        for kw in ["日值","旬值","月值","年值","daily","monthly","yearly","day","month","year"]:
            if kw in t:
                return {"daily":"日值","monthly":"月值","yearly":"年值"}.get(kw, kw)
        return t
    num = m.group("num")
    uni = m.group("unit").lower()
    if uni in ["m","米"]:
        unit = "m"
    elif uni in ["km","千米"]:
        unit = "km"
    elif uni in ["°","度","deg"]:
        unit = "°"
    elif uni in ["daily","day","日","日值"]:
        return "日值"
    elif uni in ["monthly","month","月","月值"]:
        return "月值"
    elif uni in ["yearly","year","年","年值"]:
        return "年值"
    elif uni in ["h","小时"]:
        unit = "h"
        return f"{num}{unit}"
    else:
        unit = uni
    return f"{num}{unit}"

def normalize_location(text: str) -> str:
    if not text:
        return ""
    t = str(text)
    for patt, canon in LOC_MAP.items():
        if re.search(patt, t, re.I):
            return canon
    return t

# =========================
# 业务知识库（可持续扩充）
# =========================

DATA_KB: Dict[str, Dict] = {
    "IWED": {"institution": "TFDD（俄勒冈州立大学）", "dataset_authors":"", "doi":"", "dataset_summary": "全球跨境水事件数据库"},
    "TFDD": {"institution": "俄勒冈州立大学", "dataset_authors":"", "doi":"", "dataset_summary": "跨境淡水争端项目数据库"},
    "TWAP": {"institution": "联合国环境署", "dataset_authors":"", "doi":"", "dataset_summary": "跨界水评估项目数据库"},
    "WRI Aqueduct": {"institution": "世界资源研究所（WRI）", "dataset_authors":"", "doi":"", "dataset_summary": "全球水风险评估数据"},
    "CHIRPS": {"institution": "UCSB/CHC", "dataset_authors":"", "doi":"", "dataset_summary": "卫星与站点融合降水产品（1981-）"},
    "MOD11A2": {"institution": "NASA", "dataset_authors":"", "doi":"", "dataset_summary": "MODIS 地表温度 8日合成"},
    "MCD12Q1": {"institution": "NASA", "dataset_authors":"", "doi":"", "dataset_summary": "MODIS 土地覆盖年产品"},
    "SRTM DEM": {"institution": "NASA/JPL", "dataset_authors":"", "doi":"", "dataset_summary": "航天飞机雷达测高地形数据"},
    "WorldPop": {"institution": "WorldPop/南安普顿大学", "dataset_authors":"", "doi":"", "dataset_summary": "全球人口网格数据"},
    "GLDAS": {"institution": "NASA/GSFC", "dataset_authors":"", "doi":"", "dataset_summary": "全球陆地数据同化系统"},
    "CRU": {"institution": "东英格利亚大学", "dataset_authors":"", "doi":"", "dataset_summary": "格点化气候数据"},
    "ERA5-LAND": {"institution": "ECMWF", "dataset_authors":"", "doi":"", "dataset_summary": "高分辨率陆面再分析"},
}

def enrich_from_kb(item: Dict) -> Dict:
    name = canonicalize(item.get("name", ""))
    if not name:
        return item
    kb = DATA_KB.get(name)
    if not kb:
        return item
    if not item.get("institution") and kb.get("institution"):
        item["institution"] = kb["institution"]
    if not item.get("doi") and kb.get("doi"):
        item["doi"] = kb["doi"]
    if not item.get("dataset_summary") and kb.get("dataset_summary"):
        item["dataset_summary"] = kb["dataset_summary"]
    if not item.get("dataset_authors") and kb.get("dataset_authors"):
        item["dataset_authors"] = kb["dataset_authors"]
    return item

def merge_by_name(items: List[Dict]) -> List[Dict]:
    bag: Dict[str, Dict] = {}
    for it in items or []:
        name = canonicalize(it.get("name", "").strip())
        if not name:
            name = f"__unknown__:{id(it)}"

        time_norm = normalize_time_range(it.get("time_range", ""))
        res_norm  = normalize_resolution(it.get("resolution", ""))
        loc_norm  = normalize_location(it.get("location", ""))

        it["name"] = name
        if time_norm: it["time_range"] = time_norm
        if res_norm:  it["resolution"] = res_norm
        if loc_norm:  it["location"] = loc_norm

        acc = bag.setdefault(name, {
            "name": name, "evidence": [], "variables": [],
            "derived_from": [], "validated_by": []
        })

        for f in [
            "type","source","time_range","resolution","doi","source_url",
            "dataset_authors","institution","location","dataset_summary","verified","data_role"
        ]:
            acc[f] = _best(acc.get(f,""), it.get(f,""))

        for f in ["variables","derived_from","validated_by"]:
            acc[f] = _dedup_list((acc.get(f,[]) or []) + (it.get(f,[]) or []))

        acc["evidence"] = dedup_evidence((acc.get("evidence",[]) or []) + (it.get("evidence",[]) or []))

        try:
            acc["confidence"] = max(float(acc.get("confidence", 0.0)), float(it.get("confidence", 0.0)))
        except Exception:
            acc["confidence"] = float(acc.get("confidence", 0.0)) or 0.0

        acc = enrich_from_kb(acc)

        bag[name] = acc

    return list(bag.values())

def enforce_expected_items(full_text: str, items: List[Dict]) -> List[Dict]:
    txt = full_text or ""
    def has_kw(kw: str) -> bool:
        return (kw in txt) or any(kw in (x.get("name","") + x.get("dataset_summary","")) for x in items)

    if has_kw("ERA5-LAND"):
        already = any(("逐日地表温度" in (x.get("name","") + x.get("dataset_summary",""))) for x in items)
        if not already:
            items.append({
                "name": "逐日地表温度(ERA5-LAND衍生)",
                "type": "derived",
                "source": "generated",
                "data_role": "output",
                "time_range": "",
                "resolution": "日值",
                "derived_from": ["ERA5-LAND"],
                "dataset_summary": "由ERA5-LAND逐小时0–7cm土壤温度统计得到的逐日地表温度",
                "confidence": 0.6,
                "verified": items[0].get("verified","unverified") if items else "unverified"
            })
    return items

RE_OUTPUT_TRIGGER = re.compile(r"(驱动|基于|利用).{0,60}?(得到|生成|模拟|反演).{0,30}?(结果|数据)", re.S)
RE_MODEL = re.compile(
    r"\b(CLM(?:\s*4\.5|[0-9](?:\.[0-9])?)|CLM|WRF|DSSAT|SWAT|Noah[-\s]?MP|Noah|VIC|SiB|CommonLandModel)\b",
    re.I
)
RE_GRID = re.compile(r"\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:°|deg|度)", re.I)

def add_model_output_if_present(full_text: str, items: List[dict]) -> List[dict]:
    txt = full_text or ""
    if not RE_OUTPUT_TRIGGER.search(txt):
        return items
    m_model = RE_MODEL.search(txt)
    model = (m_model.group(0).strip() if m_model else "模型").upper()
    m_res = RE_GRID.search(txt)
    grid_res = m_res.group(0).replace("deg", "°") if m_res else ""
    tm = normalize_time_range(txt)

    inputs = []
    for it in items:
        n = canonicalize(it.get("name",""))
        if n in {"CRU","CRUNCEP","ERA5-LAND","ERA5","GLDAS","NCEP","MERRA2"}:
            inputs.append(n)
    inputs = list(dict.fromkeys(inputs))

    items.append({
        "name": f"{model} 模拟/反演结果",
        "type": "derived",
        "source": "generated",
        "data_role": "output",
        "time_range": tm,
        "resolution": grid_res or "月值",
        "derived_from": inputs,
        "dataset_summary": f"由外部气象/再分析资料驱动 {model} 得到的时空模拟/反演结果",
        "location": "全球",
        "confidence": 0.6,
        "verified": "unverified"
    })
    return items

# 通过 GEE 资产补齐 source_url（若缺失）
def annotate_via_gee(full_text: str, items: List[Dict]) -> List[Dict]:
    assets = [m.group(1) for m in RE_GEE_ASSET.finditer(full_text or "")]
    if not assets:
        return items
    for it in items:
        if not it.get("source_url"):
            # 仅做标注，不改变语义：以 gee:// 前缀作区分
            it["source_url"] = f"gee://{assets[0]}"
            break
    return items

_TIME_TOKEN = re.compile(r"(?:19|20)\d{2}")
_TIME_RANGE2 = re.compile(r"(?:19|20)\d{2}\s*[-—–~至到]\s*(?:19|20)\d{2}")
_SEP = re.compile(r"[,\u3001;；/、]+")

def _parse_time_pieces(time_text: str) -> List[str]:
    if not time_text:
        return []
    t = str(time_text).replace("—","-").replace("–","-").replace("~","-").replace("至","-").replace("到","-")
    parts = _SEP.split(t)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out

def _is_range(piece: str) -> bool:
    return bool(_TIME_RANGE2.fullmatch(piece.strip()))

def _is_year(piece: str) -> bool:
    return bool(_TIME_TOKEN.fullmatch(piece.strip()))

def _expand_year_range(piece: str) -> List[str]:
    try:
        a, b = [int(x) for x in piece.split("-")]
        if a > b:
            a, b = b, a
        return [str(y) for y in range(a, b+1)]
    except Exception:
        return [piece]

def explode_by_time(item: Dict, granularity: str = "year", max_splits: int = 50) -> List[Dict]:
    tr = (item.get("time_range") or "").strip()
    if not tr:
        return [item]
    pieces = _parse_time_pieces(tr)
    if not pieces:
        return [item]
    out: List[Dict] = []
    if granularity == "range":
        for p in pieces:
            ni = dict(item)
            ni["time_range"] = p
            ni["name"] = f'{item.get("name","")}'.strip()
            out.append(ni)
        return out

    years: List[str] = []
    for p in pieces:
        pp = p.strip()
        if not pp:
            continue
        if _is_range(pp):
            years.extend(_expand_year_range(pp))
        elif _is_year(pp):
            years.append(pp)
        else:
            m = _TIME_TOKEN.search(pp)
            if m:
                years.append(m.group(0))
            else:
                years.append(pp)
    try:
        years = sorted(set(years), key=lambda x: int(_TIME_TOKEN.search(x).group(0)) if _TIME_TOKEN.search(x) else x)
    except Exception:
        years = list(dict.fromkeys(years))

    if len(years) > max_splits:
        return [item]

    for y in years:
        ni = dict(item)
        ni["time_range"] = y
        ni["name"] = f'{item.get("name","")}'.strip()
        out.append(ni)
    return out

def post_normalize(full_text: str, data_resources: List[Dict]) -> List[Dict]:
    # 1) 合并/规范
    merged = merge_by_name(data_resources or [])

    # 2) 期望项补齐
    enriched = enforce_expected_items(full_text, merged)

    # 3) 模型产出数据自动补齐
    enriched = add_model_output_if_present(full_text, enriched)

    # 3.5) GEE 标注（若识别到资产）
    enriched = annotate_via_gee(full_text, enriched)

    # 4) 再合并一遍
    merged2 = merge_by_name(enriched)

    # 5) 按年拆分
    exploded: List[Dict] = []
    for it in merged2:
        exploded.extend(explode_by_time(it, granularity="year", max_splits=50))

    # 6) 最后合并一次
    final = merge_by_name(exploded)

    return final
