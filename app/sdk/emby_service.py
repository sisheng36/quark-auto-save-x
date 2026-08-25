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
                        result["in_library"] = True
                        result["seasons"] = best.get("season_numbers", "")
                        result["matched_name"] = best.get("name", "")
                        status_map[status_key] = result
                        continue
            # 3. 未匹配
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
