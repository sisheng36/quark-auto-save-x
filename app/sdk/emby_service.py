#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emby 媒体库服务模块
用于定时拉取 Emby 媒体库数据到本地缓存，并在影视发现页匹配入库状态。
"""

import re
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 只匹配标题末尾的季后缀，避免误伤中间带「季」的名字。
_SEASON_SUFFIX_RE = re.compile(
    r'(?:'
    r'[\s\u3000.\-—_]*第\s*(?P<cn>[0-9]{1,2}|[一二三四五六七八九十零两〇]{1,4})\s*季'
    r'|[\s\u3000.\-—_]*[Ss]eason\s*(?P<en>\d{1,2})'
    r'|[\s\u3000.\-—_]*[Ss](?P<s>\d{1,2})(?:[Ee]\d{1,3})?'
    r')$'
)
_CN_DIGITS = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
}


class EmbyService:
    def __init__(self, url: str = "", token: str = ""):
        self.url = url or ""
        self.token = token or ""
        # 标准化 URL，避免末尾斜杠导致路径拼接出现 //
        if self.url:
            self.url = self.url.strip()
            if not self.url.startswith(("http://", "https://")):
                self.url = f"http://{self.url}"
            self.url = self.url.rstrip("/")
        # 复用会话，开启重试
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5,
                        status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=["GET"])
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.last_error = None

    @classmethod
    def from_config(cls, config_data: dict) -> "EmbyService":
        """从 config_data 中读取 Emby 插件配置并实例化"""
        plugins = config_data.get('plugins', {}) if isinstance(config_data, dict) else {}
        emby_cfg = plugins.get('emby', {})
        url = emby_cfg.get('url', '')
        token = emby_cfg.get('token', '')
        return cls(url=url, token=token)

    def is_configured(self) -> bool:
        """检查 Emby 是否已配置（url + token 均非空）"""
        return bool(self.url and self.token)

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """发送 GET 请求到 Emby"""
        url = f"{self.url}/emby/{endpoint.lstrip('/')}"
        headers = {"X-Emby-Token": self.token}
        try:
            response = self.session.get(url, headers=headers, params=params or {}, timeout=30)
            if response.status_code == 200 and 'application/json' in response.headers.get('Content-Type', ''):
                return response.json()
            else:
                self.last_error = f"Emby 请求失败 HTTP {response.status_code}"
                logger.warning(f"Emby 请求失败: {url} -> {response.status_code}")
                return None
        except Exception as e:
            self.last_error = str(e)
            logger.warning(f"Emby 请求出错: {e}")
            return None

    # ==================== 数据拉取 ====================

    def fetch_library_items(self) -> List[dict]:
        """分页拉取所有 Series + Movie，含 ProviderIds、ProductionYear"""
        all_items = []
        start_index = 0
        page_size = 1000
        while True:
            data = self._get("Items", {
                "Recursive": "true",
                "IncludeItemTypes": "Series,Movie",
                "Fields": "ProviderIds,ProductionYear",
                "StartIndex": start_index,
                "Limit": page_size,
            })
            if not data:
                break
            items = data.get("Items", [])
            total = data.get("TotalRecordCount", 0)
            all_items.extend(items)
            start_index += page_size
            if start_index >= total or not items:
                break
        return all_items

    def fetch_seasons(self, series_emby_id: str) -> List[int]:
        """拉取某 Series 的季号列表"""
        data = self._get("Items", {
            "ParentId": series_emby_id,
            "IncludeItemTypes": "Season",
            "Fields": "IndexNumber",
            "SortBy": "IndexNumber",
            "SortOrder": "Ascending",
        })
        if not data:
            return []
        seasons = []
        for item in data.get("Items", []):
            idx = item.get("IndexNumber")
            if idx is not None:
                seasons.append(int(idx))
        return sorted(seasons)

    def refresh_local_cache(self, cal_db) -> dict:
        """
        全量拉取 Emby 媒体库数据并写入本地缓存。
        返回 {success, count, message}
        """
        if not self.is_configured():
            return {"success": False, "count": 0, "message": "Emby 未配置"}
        try:
            raw_items = self.fetch_library_items()
            if not raw_items:
                return {"success": False, "count": 0, "message": "Emby 媒体库为空或拉取失败"}
            now = int(time.time())
            normalized = []
            for raw in raw_items:
                emby_id = str(raw.get("Id", ""))
                if not emby_id:
                    continue
                item_type = raw.get("Type", "")
                provider_ids = raw.get("ProviderIds", {}) or {}
                provider_tmdb = str(provider_ids.get("Tmdb", "") or "")
                provider_imdb = str(provider_ids.get("Imdb", "") or "")
                provider_tvdb = str(provider_ids.get("Tvdb", "") or "")
                year = str(raw.get("ProductionYear", "") or "")
                name = raw.get("Name", "") or ""
                original_title = raw.get("OriginalTitle", "") or ""
                season_numbers = ""
                # Series 才拉取季信息
                if item_type == "Series":
                    seasons = self.fetch_seasons(emby_id)
                    season_numbers = ",".join(str(s) for s in seasons)
                normalized.append({
                    "emby_id": emby_id,
                    "name": name,
                    "original_title": original_title,
                    "year": year,
                    "item_type": item_type,
                    "provider_tmdb": provider_tmdb,
                    "provider_imdb": provider_imdb,
                    "provider_tvdb": provider_tvdb,
                    "season_numbers": season_numbers,
                    "last_updated": now,
                })
            # 全量替换：清空旧数据 → 写入新数据
            cal_db.clear_emby_items()
            cal_db.upsert_emby_items_batch(normalized)
            logger.info(f"Emby 媒体库缓存已更新，共 {len(normalized)} 条")
            return {"success": True, "count": len(normalized), "message": f"已缓存 {len(normalized)} 条"}
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"刷新 Emby 媒体库缓存失败: {e}")
            return {"success": False, "count": 0, "message": f"刷新失败: {e}"}

    # ==================== 匹配逻辑 ====================

    @staticmethod
    def _normalize_title(title: str) -> str:
        """标题规范化：去空格、统一半角、转小写"""
        if not title:
            return ""
        # 全角转半角
        result = title
        for full, half in zip('　０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ',
                              ' 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
            result = result.replace(full, half)
        # 小写 + 去除首尾空格和标点
        result = result.lower().strip()
        result = re.sub(r'[\s\u3000]+', '', result)
        result = re.sub(r'[:：·・\-—_.,，。!！?？\'"()（）\[\]【】]+', '', result)
        return result

    @staticmethod
    def _chinese_numeral_to_int(text: str) -> Optional[int]:
        """将 1–99 的中文数字转为整数，无法识别则返回 None。"""
        if not text:
            return None
        if text.isdigit():
            try:
                return int(text)
            except (ValueError, TypeError):
                return None
        if text == '十':
            return 10
        if text.startswith('十'):
            ones = _CN_DIGITS.get(text[1:])
            return 10 + ones if ones is not None else None
        if '十' in text:
            left, _, right = text.partition('十')
            tens = _CN_DIGITS.get(left)
            if tens is None:
                return None
            if not right:
                return tens * 10
            ones = _CN_DIGITS.get(right)
            return tens * 10 + ones if ones is not None else None
        return _CN_DIGITS.get(text)

    @classmethod
    def _split_season_suffix(cls, title: str):
        """
        从标题末尾剥离季后缀。
        返回 (剧名, 季号)；没有可识别的季后缀时季号为 None，剧名保持原样。
        """
        if not title:
            return "", None
        raw = title.strip()
        match = _SEASON_SUFFIX_RE.search(raw)
        if not match:
            return raw, None
        season = None
        cn = match.group('cn')
        if cn:
            season = cls._chinese_numeral_to_int(cn) if not cn.isdigit() else int(cn)
        elif match.group('en'):
            season = int(match.group('en'))
        elif match.group('s'):
            season = int(match.group('s'))
        base = raw[:match.start()].strip()
        base = re.sub(r'[\s\u3000.\-—_]+$', '', base)
        if not base or season is None or season <= 0:
            return raw, None
        return base, season

    @staticmethod
    def _is_movie_item(di: dict) -> bool:
        content_type = (di.get("content_type") or "")
        media_type = (di.get("media_type") or "")
        return content_type == "movie" or media_type == "movie"

    @staticmethod
    def _parse_season_numbers(season_numbers: str) -> list:
        seasons = []
        for part in str(season_numbers or "").split(","):
            part = part.strip()
            if part.isdigit():
                seasons.append(int(part))
        return seasons

    @classmethod
    def _is_season_in_library(cls, matched: dict, season_number: Optional[int]) -> bool:
        """卡片带季号且缓存有季列表时，该季在列表中才算已入库；否则剧集命中即已入库。"""
        if season_number is None:
            return True
        seasons = cls._parse_season_numbers(matched.get("season_numbers", ""))
        if not seasons:
            return True
        return int(season_number) in seasons

    @staticmethod
    def _result_from_match(matched: dict, in_library: bool) -> dict:
        return {
            "in_library": in_library,
            "seasons": matched.get("season_numbers", "") or "",
            "matched_name": matched.get("name", "") or "",
        }

    def match_items(self, discovery_items: List[dict], cal_db) -> dict:
        """
        批量匹配 discovery items 的入库状态。
        discovery_items: [{title, year, tmdb_id, media_type, content_type}, ...]
        返回 {status_key: {in_library, seasons, matched_name}}
        """
        if not discovery_items:
            return {}
        # 一次性读入全部 Emby 缓存到内存
        all_emby = cal_db.get_all_emby_items()
        if not all_emby:
            return {}

        # 构建 TMDB 索引: {(tmdb_id, item_type): item}
        tmdb_index = {}
        # 构建标题索引: {normalized_title: [item, ...]}
        title_index = {}
        for item in all_emby:
            tmdb = item.get("provider_tmdb", "")
            item_type = item.get("item_type", "")
            if tmdb:
                tmdb_index[(tmdb, item_type)] = item
            for key in (item.get("name", ""), item.get("original_title", "")):
                if key:
                    norm = self._normalize_title(key)
                    if norm:
                        title_index.setdefault(norm, []).append(item)

        status_map = {}
        for di in discovery_items:
            status_key = self._make_status_key(di)
            result = {"in_library": False, "seasons": "", "matched_name": ""}
            # 1. TMDB ID 精确匹配
            tmdb_id = di.get("tmdb_id")
            media_type = di.get("media_type", "")
            content_type = di.get("content_type", "")
            if tmdb_id:
                tmdb_str = str(int(tmdb_id)) if not isinstance(tmdb_id, str) else tmdb_id
                # 根据 media_type 推断期望的 item_type
                # movie -> Movie, tv/anime/variety/documentary -> Series
                expected_types = ["Movie"] if content_type == "movie" or media_type == "movie" else ["Series"]
                matched = None
                for et in expected_types:
                    if (tmdb_str, et) in tmdb_index:
                        matched = tmdb_index[(tmdb_str, et)]
                        break
                # 如果类型不匹配，也兜底查一次任意类型（tmdb id 唯一性较高时）
                if not matched:
                    for (tid, _), item in tmdb_index.items():
                        if tid == tmdb_str:
                            matched = item
                            break
                if matched:
                    result["in_library"] = True
                    result["seasons"] = matched.get("season_numbers", "")
                    result["matched_name"] = matched.get("name", "")
                    status_map[status_key] = result
                    continue
            # 2. 标题+年份模糊匹配（豆瓣榜单卡无 tmdb_id）
            title = di.get("title", "")
            year = di.get("year", "")
            if title:
                norm_title = self._normalize_title(title)
                candidates = title_index.get(norm_title, [])
                if candidates:
                    best = self._pick_best_candidate(candidates, year)
                    if best:
                        status_map[status_key] = self._result_from_match(best, True)
                        continue
                # 3. 剥掉末尾季后缀后再匹配（豆瓣「末日地堡 第三季」对 Emby Series「末日地堡」）
                if not self._is_movie_item(di):
                    base_title, season_number = self._split_season_suffix(title)
                    if season_number is not None:
                        norm_base = self._normalize_title(base_title)
                        if norm_base and norm_base != norm_title:
                            base_candidates = title_index.get(norm_base, [])
                            if base_candidates:
                                best = self._pick_series_candidate(base_candidates)
                                if best:
                                    in_library = self._is_season_in_library(best, season_number)
                                    status_map[status_key] = self._result_from_match(best, in_library)
                                    continue
            # 4. 未匹配
            status_map[status_key] = result
        return status_map

    @staticmethod
    def _make_status_key(di: dict) -> str:
        """生成与前端一致的匹配 key"""
        tmdb_id = di.get("tmdb_id")
        media_type = di.get("media_type", "")
        if tmdb_id:
            tmdb_str = str(int(tmdb_id)) if not isinstance(tmdb_id, str) else tmdb_id
            if media_type:
                return f"tmdb-{media_type}-{tmdb_str}"
            return f"tmdb-{tmdb_str}"
        # 豆瓣卡用 title-year 做 key
        title = di.get("title", "")
        year = di.get("year", "")
        return f"title-{title}-{year}"

    def _pick_best_candidate(self, candidates: list, year: str) -> Optional[dict]:
        """从候选条目中挑选年份最接近的"""
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if not year:
            # 无年份参考，返回第一个
            return candidates[0]
        try:
            target_year = int(year)
        except (ValueError, TypeError):
            return candidates[0]
        best = None
        best_diff = 999
        for item in candidates:
            try:
                item_year = int(item.get("year", "") or "")
            except (ValueError, TypeError):
                continue
            diff = abs(item_year - target_year)
            if diff <= 1 and diff < best_diff:
                best = item
                best_diff = diff
        return best or candidates[0]

    @staticmethod
    def _pick_series_candidate(candidates: list) -> Optional[dict]:
        """剥季匹配：优先 Series，不去掉年份差过大的候选（分季年份 ≠ 开播年）。"""
        if not candidates:
            return None
        unique = []
        seen = set()
        for item in candidates:
            emby_id = item.get("emby_id")
            key = emby_id if emby_id else id(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        series = [item for item in unique if item.get("item_type") == "Series"]
        pool = series or unique
        return pool[0]
