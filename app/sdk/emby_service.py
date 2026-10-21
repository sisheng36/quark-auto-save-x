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
from typing import List, Optional

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
        """分页拉取所有 Series + Movie + Season，含 ProviderIds、ProductionYear。

        季条目一起拉：季这一级通常没有 ProviderIds（实测 1577 季里 0 个有 Imdb），
        但季号与 SeriesId 是后续「IMDb 反查 → 季号」落库需要的。
        """
        all_items = []
        start_index = 0
        page_size = 1000
        while True:
            data = self._get("Items", {
                "Recursive": "true",
                "IncludeItemTypes": "Series,Movie,Season",
                "Fields": "ProviderIds,ProductionYear,SeriesId,IndexNumber,ParentId",
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

    def lookup_by_imdb(self, imdb_id: str) -> Optional[dict]:
        """按 IMDb ID 反查 Emby 条目（AnyProviderIdEquals）。

        豆瓣多季剧集的条目里填的是「该季第一集」的 IMDb，整剧 Series 上并没有这个 ID，
        所以只能反查。返回：
          {item_type, emby_id, series_emby_id, season_number}
        item_type 为 Series 表示这是整剧 ID；为 Episode 时 season_number 即该集所在季。
        """
        imdb_id = str(imdb_id or "").strip().lower()
        if not imdb_id:
            return None
        data = self._get("Items", {
            "Recursive": "true",
            "AnyProviderIdEquals": f"imdb.{imdb_id}",
            "Fields": "ProviderIds,SeriesId,ParentIndexNumber,IndexNumber",
            "Limit": 10,
        })
        if not data:
            return None
        items = data.get("Items") or []
        if not items:
            return None
        # 这个 ID 本身就挂在 Series 上 → 整剧 ID，按整剧匹配（S1 也走这条，无需季级兜底）
        series_own = [
            it for it in items
            if it.get("Type") == "Series"
            and self._normalize_imdb_id((it.get("ProviderIds") or {}).get("Imdb", "")) == imdb_id
        ]
        if series_own:
            return {
                "item_type": "Series",
                "emby_id": str(series_own[0].get("Id", "")),
                "series_emby_id": str(series_own[0].get("Id", "")),
                "season_number": None,
            }
        # 否则这是「某一季第一集」的 ID：优先取第 2 季及以后的集，
        # 第 1 季的季 IMDb 与整剧 ID 容易混淆，且 S1 本来就能靠整剧匹配命中。
        episodes = [it for it in items if it.get("Type") == "Episode"]
        later_seasons = [
            it for it in episodes
            if (it.get("ParentIndexNumber") or 0) >= 2 and it.get("SeriesId")
        ]
        picked = None
        if later_seasons:
            later_seasons.sort(key=lambda it: (it.get("ParentIndexNumber") or 0, it.get("IndexNumber") or 0))
            picked = later_seasons[0]
        elif episodes:
            episodes.sort(key=lambda it: (it.get("ParentIndexNumber") or 0, it.get("IndexNumber") or 0))
            picked = episodes[0]
        if picked:
            return {
                "item_type": "Episode",
                "emby_id": str(picked.get("Id", "")),
                "series_emby_id": str(picked.get("SeriesId", "") or ""),
                "season_number": int(picked.get("ParentIndexNumber") or 0) or None,
            }
        series = [it for it in items if it.get("Type") == "Series"]
        if series:
            return {
                "item_type": "Series",
                "emby_id": str(series[0].get("Id", "")),
                "series_emby_id": str(series[0].get("Id", "")),
                "season_number": None,
            }
        return None

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
            # 季条目只在内存里映射，本身不写入缓存表
            seasons_by_series = {}
            for raw in raw_items:
                if raw.get("Type") != "Season":
                    continue
                series_emby_id = str(raw.get("SeriesId", "") or raw.get("ParentId", "") or "")
                idx = raw.get("IndexNumber")
                if not series_emby_id or idx is None:
                    continue
                seasons_by_series.setdefault(series_emby_id, set()).add(int(idx))

            # 旧缓存的季级 IMDb：季列表没变就沿用，避免每次刷新都重新反查
            previous = {}
            try:
                previous = cal_db.get_emby_season_imdb_map() or {}
            except Exception as e:
                logger.warning(f"读取上次季级 IMDb 缓存失败: {e}")

            normalized = []
            for raw in raw_items:
                emby_id = str(raw.get("Id", ""))
                if not emby_id:
                    continue
                item_type = raw.get("Type", "")
                if item_type == "Season":
                    continue
                provider_ids = raw.get("ProviderIds", {}) or {}
                provider_tmdb = str(provider_ids.get("Tmdb", "") or "")
                provider_imdb = str(provider_ids.get("Imdb", "") or "")
                provider_tvdb = str(provider_ids.get("Tvdb", "") or "")
                year = str(raw.get("ProductionYear", "") or "")
                name = raw.get("Name", "") or ""
                original_title = raw.get("OriginalTitle", "") or ""
                season_numbers = ""
                season_imdb_ids = ""
                if item_type == "Series":
                    seasons = sorted(seasons_by_series.get(emby_id) or self.fetch_seasons(emby_id))
                    season_numbers = ",".join(str(s) for s in seasons)
                    cached = previous.get(emby_id) or {}
                    # 季列表没变 → 直接复用上次反查结果
                    if cached.get("season_numbers") == season_numbers:
                        season_imdb_ids = cached.get("season_imdb_ids", "") or ""
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
                    "season_imdb_ids": season_imdb_ids,
                    "last_updated": now,
                })
            # 全量替换：清空旧数据 → 写入新数据
            cal_db.clear_emby_items()
            cal_db.upsert_emby_items_batch(normalized)
            logger.info(f"Emby 媒体库缓存已更新，共 {len(normalized)} 条")
            filled = self._fill_season_imdb_ids(cal_db, normalized)
            message = f"已缓存 {len(normalized)} 条"
            if filled:
                message += f"，补全 {filled} 部剧的季 IMDb"
            return {"success": True, "count": len(normalized), "message": message}
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"刷新 Emby 媒体库缓存失败: {e}")
            return {"success": False, "count": 0, "message": f"刷新失败: {e}"}

    def _fill_season_imdb_ids(self, cal_db, normalized: List[dict],
                              budget: int = 400, workers: int = 8) -> int:
        """为「第 2 季及以后、且还没记录季 IMDb」的剧集补全季级 IMDb。

        思路（实测 Emby 4.10）：季条目没有 Imdb，集上写的是单集 IMDb，而豆瓣季条目
        填的正是「该季第一集」的 IMDb。所以按季取第一集，读出它的 IMDb 就是季 ID。
        每季只发 1 个 Limit=1 的小请求，不拉全量集；并发跑，单部剧几毫秒。
        budget 兜底限制单轮最多补多少部剧，剩下的下次刷新继续。
        """
        pending = []
        for item in normalized:
            if item.get("item_type") != "Series":
                continue
            if item.get("season_imdb_ids"):
                continue
            seasons = [int(s) for s in str(item.get("season_numbers", "")).split(",")
                       if s.strip().isdigit()]
            if any(s >= 2 for s in seasons):
                pending.append(item)
        if not pending:
            return 0

        targets = pending[:max(0, int(budget))]
        mapping_by_id = {}
        if targets:
            from concurrent.futures import ThreadPoolExecutor
            try:
                with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(targets)))) as pool:
                    futures = {
                        pool.submit(self._fetch_season_imdb_ids, item["emby_id"]): item
                        for item in targets
                    }
                    for future, item in futures.items():
                        try:
                            mapping = future.result()
                        except Exception as e:
                            logger.debug(f"补全季 IMDb 失败 {item.get('name')}: {e}")
                            continue
                        if mapping:
                            mapping_by_id[item["emby_id"]] = mapping
            except Exception as e:
                logger.warning(f"季 IMDb 并发补全不可用，改为串行: {e}")
                for item in targets:
                    try:
                        mapping = self._fetch_season_imdb_ids(item["emby_id"])
                    except Exception:
                        continue
                    if mapping:
                        mapping_by_id[item["emby_id"]] = mapping

        updated = []
        for item in targets:
            mapping = mapping_by_id.get(item["emby_id"])
            if not mapping:
                continue
            item["season_imdb_ids"] = mapping
            updated.append({"emby_id": item["emby_id"], "season_imdb_ids": mapping})
        if not updated:
            return 0
        try:
            cal_db.upsert_emby_season_imdb_batch(updated)
        except Exception as e:
            logger.warning(f"写入季级 IMDb 失败: {e}")
            return 0
        return len(updated)

    def _fetch_season_imdb_ids(self, series_emby_id: str) -> str:
        """读某剧第 2 季起每季第一集的 IMDb，拼成 "2:tt123,3:tt456"（失败返回空串）。"""
        data = self._get("Items", {
            "ParentId": series_emby_id,
            "IncludeItemTypes": "Season",
            "Fields": "IndexNumber",
            "SortBy": "IndexNumber",
            "SortOrder": "Ascending",
        })
        if not data:
            return ""
        seasons = []
        for season in data.get("Items") or []:
            idx = season.get("IndexNumber")
            if idx is None or int(idx) < 2:
                continue
            seasons.append((int(idx), str(season.get("Id", "") or "")))
        pairs = []
        for number, season_emby_id in sorted(seasons):
            if not season_emby_id:
                continue
            episodes = self._get("Items", {
                "ParentId": season_emby_id,
                "IncludeItemTypes": "Episode",
                "Fields": "ProviderIds",
                "SortBy": "ParentIndexNumber,IndexNumber",
                "SortOrder": "Ascending",
                "Limit": 1,
            })
            items = (episodes or {}).get("Items") or []
            if not items:
                continue
            imdb = self._normalize_imdb_id(
                (items[0].get("ProviderIds") or {}).get("Imdb", ""))
            if imdb:
                pairs.append(f"{number}:{imdb}")
        return ",".join(pairs)

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

    @staticmethod
    def _parse_season_imdb_ids(raw: str) -> dict:
        """解析「季号 → 季级 IMDb」："2:tt123,3:tt456" → {2: 'tt123', 3: 'tt456'}"""
        mapping = {}
        for part in str(raw or "").split(","):
            number, _, imdb = part.partition(":")
            number = number.strip()
            imdb = imdb.strip().lower()
            if not number.isdigit() or not imdb:
                continue
            mapping[int(number)] = imdb
        return mapping

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
    def _result_from_match(matched: dict, in_library: bool, match_by: str = "title") -> dict:
        return {
            "in_library": in_library,
            "seasons": matched.get("season_numbers", "") or "",
            "matched_name": matched.get("name", "") or "",
            "match_by": match_by,
        }

    @classmethod
    def _title_candidate_allowed(cls, candidate: dict, imdb_id: str,
                                 season_number: Optional[int] = None) -> bool:
        """标题命中但双方都有 IMDb 且不一致时，判断是不是同名不同片。

        多季剧集有个坑：豆瓣条目填的是「这一季」的 IMDb（= 该季第一集的 IMDb），
        而 Emby 的 Series 上挂的是整剧 ID，两者本来就不相等。若直接用「不相等就拦截」，
        多季剧集会被全部误判成未入库。所以：
          1) 整剧 ID 相等 → 同一部剧；
          2) 卡片带季号、且该季的季级 IMDb 与卡片一致 → 同一部剧（最硬的证据）；
          3) 卡片带季号、但这部剧本季没取到季级 IMDb（实测约 78% 的剧集上没有 IMDb）
             → 只要这部剧本季确实在库，就认标题命中。季级 IMDb 只是加强证据，
             取不到时不能因此把已入库判成未入库；
          4) 卡片不带季号 → 只有 ID 对得上该剧某一季才放行，否则仍按同名不同片拦截。
        """
        if not imdb_id:
            return True
        candidate_imdb = cls._normalize_imdb_id(candidate.get("provider_imdb", ""))
        if not candidate_imdb:
            # Emby 没刮到 IMDb，标题命中仍然可信
            return True
        if candidate_imdb == imdb_id:
            return True
        season_imdbs = cls._parse_season_imdb_ids(candidate.get("season_imdb_ids", ""))
        if season_number is None:
            # 无季号：只有 ID 等于该剧某一季的 ID 才认（避免同名不同剧误判）
            return imdb_id in season_imdbs.values() if season_imdbs else False
        known = season_imdbs.get(int(season_number))
        if known:
            # 该季有季级 IMDb 证据：必须一致
            return known == imdb_id
        # 该季没有季级 IMDb：季级证据缺失不等于不是同一部剧，
        # 退回「这一季确实在库」的判断，避免误报未入库。
        return cls._is_season_in_library(candidate, season_number)

    @staticmethod
    def _normalize_imdb_id(imdb_id) -> str:
        """IMDb ID 规范化：去空格转小写，只保留 tt 开头的编号"""
        if not imdb_id:
            return ""
        value = str(imdb_id).strip().lower()
        if not value:
            return ""
        if not value.startswith("tt"):
            value = f"tt{value}" if value.isdigit() else value
        if not re.match(r'^tt\d{5,10}$', value):
            return ""
        return value

    def _pick_imdb_candidate(self, candidates: List[dict], di: dict) -> Optional[dict]:
        """
        IMDb 命中后的候选挑选：类型优先（电影对 Movie、剧集对 Series），
        再按年份接近程度排序。剧集命中的是整部 Series，季数仍由调用方比对。
        """
        if not candidates:
            return None
        want_movie = self._is_movie_item(di)
        want_type = "Movie" if want_movie else "Series"
        typed = [item for item in candidates if item.get("item_type") == want_type]
        pool = typed or candidates
        if len(pool) == 1:
            return pool[0]
        year = str(di.get("year", "") or "")
        try:
            target_year = int(year)
        except (TypeError, ValueError):
            return pool[0]
        best = pool[0]
        best_diff = 999
        for item in pool:
            try:
                item_year = int(item.get("year", "") or "")
            except (TypeError, ValueError):
                continue
            diff = abs(item_year - target_year)
            if diff < best_diff:
                best = item
                best_diff = diff
        return best

    def match_items(self, discovery_items: List[dict], cal_db) -> dict:
        """
        批量匹配 discovery items 的入库状态。
        discovery_items: [{title, year, tmdb_id, imdb_id, media_type, content_type}, ...]
        返回 {status_key: {in_library, seasons, matched_name, match_by}}
        """
        if not discovery_items:
            return {}
        # 一次性读入全部 Emby 缓存到内存
        all_emby = cal_db.get_all_emby_items()
        if not all_emby:
            return {}

        # 构建 TMDB 索引: {(tmdb_id, item_type): item}
        tmdb_index = {}
        # 构建 IMDb 索引: {imdb_id: [item, ...]}（豆瓣与 TMDB 译名不一致时靠它兜底）
        imdb_index = {}
        # 构建标题索引: {normalized_title: [item, ...]}
        title_index = {}
        # 构建季级 IMDb 索引: {season_imdb: [(series_item, season_number), ...]}
        season_imdb_index = {}
        for item in all_emby:
            tmdb = item.get("provider_tmdb", "")
            item_type = item.get("item_type", "")
            if tmdb:
                tmdb_index[(tmdb, item_type)] = item
            imdb = self._normalize_imdb_id(item.get("provider_imdb", ""))
            if imdb:
                imdb_index.setdefault(imdb, []).append(item)
            for season_number, season_imdb in self._parse_season_imdb_ids(
                    item.get("season_imdb_ids", "")).items():
                season_imdb_index.setdefault(season_imdb, []).append((item, season_number))
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
                    result["match_by"] = "tmdb"
                    status_map[status_key] = result
                    continue
            # 2. IMDb ID 精确匹配（豆瓣条目自带 IMDb，可绕开译名差异）
            imdb_id = self._normalize_imdb_id(di.get("imdb_id", ""))
            if imdb_id:
                candidates = imdb_index.get(imdb_id, [])
                matched = self._pick_imdb_candidate(candidates, di)
                if matched:
                    # 剧集仍按季比对：IMDb ID 指向整部 Series，卡片带季号时要看该季是否入库
                    in_library = True
                    if not self._is_movie_item(di):
                        _, season_number = self._split_season_suffix(di.get("title", "") or "")
                        in_library = self._is_season_in_library(matched, season_number)
                    status_map[status_key] = self._result_from_match(matched, in_library, "imdb")
                    continue
                # 2b. 豆瓣多季条目填的是「这一季」的 IMDb（= 该季第一集的 IMDb），
                # 这个 ID 不会出现在 Series 上。按季级索引兜底，避免多季剧集全部误判未入库。
                if not self._is_movie_item(di):
                    _, season_number = self._split_season_suffix(di.get("title", "") or "")
                    for season_item, season_hit in season_imdb_index.get(imdb_id, []):
                        if season_number is not None and int(season_hit) != int(season_number):
                            continue
                        status_map[status_key] = self._result_from_match(
                            season_item, True, "imdb-season")
                        break
                    if status_key in status_map:
                        continue
            # 3. 标题+年份模糊匹配（豆瓣榜单卡无 tmdb_id）
            title = di.get("title", "")
            year = di.get("year", "")
            # 卡片标题里的季号（豆瓣多季条目形如「某某剧 第三季」），IMDb 冲突判定要用
            card_season = None
            if title and not self._is_movie_item(di):
                _, card_season = self._split_season_suffix(title)
            if title:
                norm_title = self._normalize_title(title)
                candidates = [
                    c for c in title_index.get(norm_title, [])
                    if self._title_candidate_allowed(c, imdb_id, card_season)
                ]
                if candidates:
                    best = self._pick_best_candidate(candidates, year)
                    if best:
                        status_map[status_key] = self._result_from_match(best, True, "title")
                        continue
                # 4. 剥掉末尾季后缀后再匹配（豆瓣「末日地堡 第三季」对 Emby Series「末日地堡」）
                if not self._is_movie_item(di):
                    base_title, season_number = self._split_season_suffix(title)
                    if season_number is not None:
                        norm_base = self._normalize_title(base_title)
                        if norm_base and norm_base != norm_title:
                            base_candidates = [
                                c for c in title_index.get(norm_base, [])
                                if self._title_candidate_allowed(c, imdb_id, season_number)
                            ]
                            if base_candidates:
                                best = self._pick_series_candidate(base_candidates, season_number)
                                if best:
                                    in_library = self._is_season_in_library(best, season_number)
                                    status_map[status_key] = self._result_from_match(best, in_library, "title")
                                    continue
            # 5. 未匹配
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

    @staticmethod
    def _prefer_with_imdb(candidates: list) -> list:
        """同名多部时，优先保留刮到 IMDb 的那部：它有更硬的证据，也更可能是正片。"""
        if not candidates or len(candidates) < 2:
            return candidates
        with_imdb = [c for c in candidates if str(c.get("provider_imdb") or "").strip()]
        return with_imdb or candidates

    def _pick_best_candidate(self, candidates: list, year: str) -> Optional[dict]:
        """从候选条目中挑选年份最接近的"""
        if not candidates:
            return None
        candidates = self._prefer_with_imdb(candidates)
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

    @classmethod
    def _pick_series_candidate(cls, candidates: list, season_number: Optional[int] = None) -> Optional[dict]:
        """剥季匹配：优先 Series，不去掉年份差过大的候选（分季年份 ≠ 开播年）。

        同名多部（例如 1996 与 1999 两版《西游记》）时，先排除本季不在库的候选，
        再优先刮到 IMDb 的那部，避免随手挑中重名条目导致误报未入库。
        """
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
        if season_number is not None:
            has_season = [item for item in pool if cls._is_season_in_library(item, season_number)]
            if has_season:
                pool = has_season
        pool = cls._prefer_with_imdb(pool)
        return pool[0]
