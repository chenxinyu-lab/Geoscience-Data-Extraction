# -*- coding: utf-8 -*-
from typing import Dict, List, Tuple
import regex as re

# =========================
# 别名归一（可持续扩充）自建别名库
# =========================
ALIASES = {
    r"\bIWED\b|International Water Event Database|跨境水事件数据库|国际水事件数据库": "IWED",
    r"\bTFDD\b|Transboundary Freshwater Dispute Database|跨境淡水争端数据库|跨界淡水争端项目": "TFDD",
    r"\bTWAP\b|Transboundary Waters Assessment Programme|跨界水评估项目": "TWAP",
    r"\bAqueduct\b|WRI\s*水风险|World Resources Institute Water Risk": "WRI Aqueduct",

    r"\bERA5-?LAND\b|ECMWF\s*ERA5-?LAND": "ERA5-LAND",
    r"\bGLDAS\b|Global Land Data Assimilation System|全球陆地数据同化系统": "GLDAS",
    r"\bCRU\b|Climatic Research Unit|气候研究单元": "CRU",
    r"\bCHIRPS\b|Climate Hazards Group InfraRed Precipitation with Station data": "CHIRPS",
    r"\bMOD11A2\b|MODIS\s*(?:LST|地表温度)\s*MOD11A2": "MOD11A2",
    r"\bMCD12Q1\b|MODIS\s*土地覆盖\s*MCD12Q1": "MCD12Q1",
    r"\bSRTM\b(?:\s*DEM)?|航天飞机雷达地形(?:任务)?": "SRTM DEM",
    r"\bWorldPop\b|世界人口(?:网格|数据)": "WorldPop",
}

def canonicalize(name: str) -> str:
    """将各种写法归一到规范简称（如 CRU、CHIRPS、GLDAS 等）。"""
    if not name:
        return name
    for patt, canon in ALIASES.items():
        if re.search(patt, name, re.I):
            return canon
    m = RE_MODIS_CODE.search(name or "")
    if m:
        return m.group(0)
    return name

# =========================
# 正则模式（时间/分辨率/DOI/URL/位置等）
# =========================
RE_GEE_ASSET = re.compile(r"(?:ee\.ImageCollection|ImageCollection|ee\.Image)\(['\"]([A-Za-z0-9/_\-.]+)['\"]\)")
RE_MODIS_CODE = re.compile(r"\bM[OYCD]D\d{2}[AQ]?\d?\b")

RE_TIME = re.compile(r"(19|20)\d{2}(?:\s*[—\-–]\s*(19|20)\d{2})?")
RE_DOI  = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)
RE_URL  = re.compile(r"(https?://[^\s)\]]+)", re.I)
RE_RES  = re.compile(r"(?:\b\d+(?:\.\d+)?\s*(?:m|km|°|deg|度|km2|km²|米|千米)\b|\b(?:daily|monthly|yearly|日值|旬值|月值|年值)\b)", re.I)
RE_LOC  = re.compile(r"(全球|中国|青藏高原|东北地区|长江|黄河|流域|亚洲|欧洲|Africa|Global|China)", re.I)

# ============ 捕捉“全名 (缩写)” ============
FULLNAME_WITH_ABBR = re.compile(
    r"([A-Za-z\u4e00-\u9fa5][A-Za-z0-9\u4e00-\u9fa5\s\-]+?)\s*\(([A-Z0-9\-]{2,})\)"
)
#基于命中位置扩窗，收集周边属性，比如doi时间分辨率
def extract_context(text: str, pos: int, window: int = 240) -> Dict:
    s = max(0, pos - window); e = min(len(text), pos + window)
    ctx = text[s:e]
    times = list({m.group(0).replace("–","-").replace("—","-") for m in RE_TIME.finditer(ctx)})
    res   = list({m.group(0) for m in RE_RES.finditer(ctx)})
    dois  = list({m.group(0) for m in RE_DOI.finditer(ctx)})
    urls  = list({m.group(0) for m in RE_URL.finditer(ctx)})
    locs  = list({m.group(0) for m in RE_LOC.finditer(ctx)})
    return {"times": times, "res": res, "dois": dois, "urls": urls, "locs": locs, "ctx": ctx}

def rule_extract(text: str)->Dict:
    """
    返回 LLM 的“候选包”与若干锚点，限制模型仅在候选中选择，减少幻觉。
    现在会优先把“全名（缩写）”作为数据集候选项输出。
    """
    # 全文级别候选
    times = list({m.group(0).replace("–","-").replace("—","-") for m in RE_TIME.finditer(text)})
    dois  = list({m.group(0) for m in RE_DOI.finditer(text)})
    urls  = list({m.group(0) for m in RE_URL.finditer(text)})
    res   = list({m.group(0) for m in RE_RES.finditer(text)})

    dataset_candidates: List[Dict] = []

    # 1) 先抓“全名（缩写）”，优先进入候选
    for m in FULLNAME_WITH_ABBR.finditer(text):
        fullname = m.group(1).strip()
        abbr = m.group(2).strip()
        dataset_name = f"{fullname} ({abbr})"
        ctx = extract_context(text, m.start(), window=240)
        dataset_candidates.append({
            "name": dataset_name,
            "pos": m.start(),
            "time_candidates": ctx["times"],
            "resolution_candidates": ctx["res"],
            "doi_candidates": ctx["dois"],
            "url_candidates": ctx["urls"],
            "location_candidates": ctx["locs"],
            "context": ctx["ctx"][:300]
        })

    # 2) 再按别名库扫描（避免重复，由去重处理）
    for patt in ALIASES.keys():
        for m in re.finditer(patt, text, re.I):
            name = canonicalize(m.group(0))
            ctx = extract_context(text, m.start(), window=240)
            dataset_candidates.append({
                "name": name,
                "pos": m.start(),
                "time_candidates": ctx["times"],
                "resolution_candidates": ctx["res"],
                "doi_candidates": ctx["dois"],
                "url_candidates": ctx["urls"],
                "location_candidates": ctx["locs"],
                "context": ctx["ctx"][:300]
            })

    # 3) GEE 资产
    gee_assets = [m.group(1) for m in RE_GEE_ASSET.finditer(text)]

    return {
        "time_candidates": times,
        "doi_candidates": dois,
        "url_candidates": urls,
        "resolution_candidates": res,
        "dataset_candidates": dataset_candidates,
        "gee_assets": gee_assets
    }
