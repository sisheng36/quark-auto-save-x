# -*- coding: utf-8 -*-
"""
豆瓣API服务模块
用于获取豆瓣影视榜单数据
"""

import re
import time
import logging
import requests
from typing import Dict, Optional, Any, List, Iterable

logger = logging.getLogger(__name__)

# 豆瓣 App 的「影片信息」H5 页面，条目信息里带 IMDb ID（rexxar 详情接口不含此字段）。
_DOUBAN_DESC_URL = "https://www.douban.com/doubanapp/h5/movie/{subject_id}/desc"
_IMDB_ROW_RE = re.compile(
    r'<td>\s*IMDb\s*</td>\s*<td>\s*(tt\d{5,10})\s*</td>', re.IGNORECASE
)
_TITLE_RE = re.compile(r'<title>(.*?)</title>', re.IGNORECASE | re.DOTALL)

# 缓存状态：ok=已取到 IMDb；missing=豆瓣页面本身没有 IMDb 字段；
# failed=请求失败（下次仍会重试）；not_found=豆瓣没有该条目
DOUBAN_IMDB_STATUS_OK = 'ok'
DOUBAN_IMDB_STATUS_MISSING = 'missing'
DOUBAN_IMDB_STATUS_FAILED = 'failed'
DOUBAN_IMDB_STATUS_NOT_FOUND = 'not_found'

# 缓存有效期：命中过 IMDb 的条目长期有效；未命中的隔一段时间重试
DOUBAN_IMDB_CACHE_TTL_OK = 30 * 24 * 3600
DOUBAN_IMDB_CACHE_TTL_MISS = 7 * 24 * 3600
DOUBAN_IMDB_CACHE_TTL_FAILED = 3600


class DoubanService:
    """豆瓣API服务类"""

    def __init__(self):
        self.base_url = "https://m.douban.com/rexxar/api/v2"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            'Referer': 'https://m.douban.com/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',  # 移除br，避免Brotli压缩
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        }

        # 电影榜单配置 - 4个大类，每个大类下有5个小类
        self.movie_categories = {
            '热门电影': {
                '全部': {'category': '热门', 'type': '全部'},
                '华语': {'category': '热门', 'type': '华语'},
                '欧美': {'category': '热门', 'type': '欧美'},
                '韩国': {'category': '热门', 'type': '韩国'},
                '日本': {'category': '热门', 'type': '日本'}
            },
            '最新电影': {
                '全部': {'category': '最新', 'type': '全部'},
                '华语': {'category': '最新', 'type': '华语'},
                '欧美': {'category': '最新', 'type': '欧美'},
                '韩国': {'category': '最新', 'type': '韩国'},
                '日本': {'category': '最新', 'type': '日本'}
            },
            '豆瓣高分': {
                '全部': {'category': '豆瓣高分', 'type': '全部'},
                '华语': {'category': '豆瓣高分', 'type': '华语'},
                '欧美': {'category': '豆瓣高分', 'type': '欧美'},
                '韩国': {'category': '豆瓣高分', 'type': '韩国'},
                '日本': {'category': '豆瓣高分', 'type': '日本'}
            },
            '冷门佳片': {
                '全部': {'category': '冷门佳片', 'type': '全部'},
                '华语': {'category': '冷门佳片', 'type': '华语'},
                '欧美': {'category': '冷门佳片', 'type': '欧美'},
                '韩国': {'category': '冷门佳片', 'type': '韩国'},
                '日本': {'category': '冷门佳片', 'type': '日本'}
            }
        }

        # 剧集榜单配置 - 2个大类
        self.tv_categories = {
            '最近热门剧集': {
                '综合': {'category': 'tv', 'type': 'tv'},
                '国产剧': {'category': 'tv', 'type': 'tv_domestic'},
                '欧美剧': {'category': 'tv', 'type': 'tv_american'},
                '日剧': {'category': 'tv', 'type': 'tv_japanese'},
                '韩剧': {'category': 'tv', 'type': 'tv_korean'},
                '动画': {'category': 'tv', 'type': 'tv_animation'},
                '纪录片': {'category': 'tv', 'type': 'tv_documentary'}
            },
            '最近热门综艺': {
                '综合': {'category': 'show', 'type': 'show'},
                '国内': {'category': 'show', 'type': 'show_domestic'},
                '国外': {'category': 'show', 'type': 'show_foreign'}
            }
        }


    def get_list_data(self, main_category: str, sub_category: str, limit: int = 20, start: int = 0) -> Dict[str, Any]:
        """
        获取榜单数据

        Args:
            main_category: 主分类 (movie_hot, movie_latest, etc.)
            sub_category: 子分类 (全部, 华语, 欧美, etc.)
            limit: 返回数量限制
            start: 起始位置

        Returns:
            包含榜单数据的字典
        """
        try:
            # 判断是电影还是电视剧
            if main_category.startswith('movie_'):
                return self._get_movie_ranking(main_category, sub_category, start, limit)
            elif main_category.startswith('tv_'):
                return self._get_tv_ranking(main_category, sub_category, start, limit)
            else:
                return {
                    'success': False,
                    'message': f'不支持的主分类: {main_category}',
                    'data': {'items': []}
                }

        except Exception as e:
            return {
                'success': False,
                'message': f'获取榜单数据失败: {str(e)}',
                'data': {'items': []}
            }

    def _get_movie_ranking(self, main_category: str, sub_category: str, start: int = 0, limit: int = 20) -> Dict[str, Any]:
        """获取电影榜单数据"""
        try:

            # 映射主分类到豆瓣分类
            category_mapping = {
                'movie_hot': '热门电影',
                'movie_latest': '最新电影',
                'movie_top': '豆瓣高分',
                'movie_underrated': '冷门佳片'
            }

            douban_main_category = category_mapping.get(main_category, '热门电影')

            # 获取对应的category和type
            if douban_main_category not in self.movie_categories:
                # 使用模拟数据
                mock_data = self._get_mock_movie_data()
                return {
                    'success': True,
                    'message': '获取成功（模拟数据）',
                    'data': {
                        'items': mock_data['items'][:limit],
                        'total': len(mock_data['items']),
                        'is_mock_data': True,
                        'mock_reason': '不支持的分类，使用模拟数据'
                    }
                }

            category_config = self.movie_categories[douban_main_category].get(sub_category)
            if not category_config:
                # 使用模拟数据
                mock_data = self._get_mock_movie_data()
                return {
                    'success': True,
                    'message': '获取成功（模拟数据）',
                    'data': {
                        'items': mock_data['items'][:limit],
                        'total': len(mock_data['items']),
                        'is_mock_data': True,
                        'mock_reason': '不支持的子分类，使用模拟数据'
                    }
                }

            # 构建请求参数 - 按照参考项目的逻辑处理分类参数
            params = {'start': start, 'limit': limit}

            # 根据分类映射到豆瓣API的参数
            douban_category = category_config.get('category', '热门')
            douban_type = category_config.get('type', '全部')

            # 根据不同的category和type添加特定参数（完全按照参考项目的逻辑）
            if douban_category != '热门' or douban_type != '全部':
                if douban_type != '全部':
                    params['type'] = douban_type
                if douban_category != '热门':
                    params['category'] = douban_category

            # 尝试调用豆瓣API
            try:
                url = f"{self.base_url}/subject/recent_hot/movie"

                # 创建session来自动处理gzip解压
                session = requests.Session()
                session.headers.update(self.headers)

                response = session.get(url, params=params, timeout=30)
                response.raise_for_status()

                # 检查响应内容是否为空
                if not response.text.strip():
                    raise ValueError("API返回空响应")

                data = response.json()

                # 处理豆瓣移动端API的响应格式
                items = data.get('items', []) or data.get('subjects', [])

                if not items:
                    mock_data = self._get_mock_movie_data()
                    return {
                        'success': True,
                        'message': '获取成功（模拟数据）',
                        'data': {
                            'items': mock_data['items'][:limit],
                            'total': len(mock_data['items']),
                            'is_mock_data': True,
                            'mock_reason': 'API返回空数据'
                        }
                    }

                # 处理返回的数据
                processed_items = []
                for item in items[:limit]:
                    processed_item = self._process_item(item)
                    if processed_item:
                        processed_items.append(processed_item)

                return {
                    'success': True,
                    'message': '获取成功',
                    'data': {
                        'items': processed_items,
                        'total': data.get('total', len(processed_items))
                    }
                }

            except Exception:
                mock_data = self._get_mock_movie_data()
                return {
                    'success': True,
                    'message': '获取成功（模拟数据）',
                    'data': {
                        'items': mock_data['items'][:limit],
                        'total': len(mock_data['items']),
                        'is_mock_data': True,
                        'mock_reason': 'API调用失败'
                    }
                }

        except Exception as e:
            mock_data = self._get_mock_movie_data()
            return {
                'success': True,
                'message': '获取成功（模拟数据）',
                'data': {
                    'items': mock_data['items'][:limit],
                    'total': len(mock_data['items']),
                    'is_mock_data': True,
                    'mock_reason': f'获取失败: {str(e)}'
                }
            }

    def _get_tv_ranking(self, main_category: str, sub_category: str, start: int = 0, limit: int = 20) -> Dict[str, Any]:
        """获取电视剧榜单数据"""
        try:

            # 映射主分类到豆瓣分类
            category_mapping = {
                'tv_drama': '最近热门剧集',
                'tv_variety': '最近热门综艺'
            }

            douban_main_category = category_mapping.get(main_category, '最近热门剧集')

            # 获取对应的category和type
            if douban_main_category not in self.tv_categories:
                # 使用模拟数据
                mock_data = self._get_mock_tv_data()
                return {
                    'success': True,
                    'message': '获取成功（模拟数据）',
                    'data': {
                        'items': mock_data['items'][:limit],
                        'total': len(mock_data['items']),
                        'is_mock_data': True,
                        'mock_reason': '不支持的分类，使用模拟数据'
                    }
                }

            category_config = self.tv_categories[douban_main_category].get(sub_category)
            if not category_config:
                # 使用模拟数据
                mock_data = self._get_mock_tv_data()
                return {
                    'success': True,
                    'message': '获取成功（模拟数据）',
                    'data': {
                        'items': mock_data['items'][:limit],
                        'total': len(mock_data['items']),
                        'is_mock_data': True,
                        'mock_reason': '不支持的子分类，使用模拟数据'
                    }
                }

            # 构建请求参数 - 按照参考项目的逻辑处理分类参数
            params = {'start': start, 'limit': limit}

            # 根据分类映射到豆瓣API的参数
            douban_category = category_config.get('category', 'tv')
            douban_type = category_config.get('type', 'tv')

            # 根据不同的category和type添加特定参数（完全按照参考项目的逻辑）
            if douban_category != 'tv' or douban_type != 'tv':
                if douban_type != 'tv':
                    params['type'] = douban_type
                if douban_category != 'tv':
                    params['category'] = douban_category

            # 尝试调用豆瓣API
            try:
                url = f"{self.base_url}/subject/recent_hot/tv"

                # 创建session来自动处理gzip解压
                session = requests.Session()
                session.headers.update(self.headers)

                response = session.get(url, params=params, timeout=30)
                response.raise_for_status()

                # 检查响应内容是否为空
                if not response.text.strip():
                    raise ValueError("TV API返回空响应")

                data = response.json()

                # 处理豆瓣移动端API的响应格式
                items = data.get('items', []) or data.get('subjects', [])

                if not items:
                    mock_data = self._get_mock_tv_data()
                    return {
                        'success': True,
                        'message': '获取成功（模拟数据）',
                        'data': {
                            'items': mock_data['items'][:limit],
                            'total': len(mock_data['items']),
                            'is_mock_data': True,
                            'mock_reason': 'API返回空数据'
                        }
                    }

                # 处理返回的数据
                processed_items = []
                for item in items[:limit]:
                    processed_item = self._process_item(item)
                    if processed_item:
                        processed_items.append(processed_item)

                return {
                    'success': True,
                    'message': '获取成功',
                    'data': {
                        'items': processed_items,
                        'total': data.get('total', len(processed_items))
                    }
                }

            except Exception:
                mock_data = self._get_mock_tv_data()
                return {
                    'success': True,
                    'message': '获取成功（模拟数据）',
                    'data': {
                        'items': mock_data['items'][:limit],
                        'total': len(mock_data['items']),
                        'is_mock_data': True,
                        'mock_reason': 'API调用失败'
                    }
                }

        except Exception as e:
            mock_data = self._get_mock_tv_data()
            return {
                'success': True,
                'message': '获取成功（模拟数据）',
                'data': {
                    'items': mock_data['items'][:limit],
                    'total': len(mock_data['items']),
                    'is_mock_data': True,
                    'mock_reason': f'获取失败: {str(e)}'
                }
            }

    # ==================== IMDb ID 抓取与缓存 ====================

    @staticmethod
    def _subject_id_of(item: Dict[str, Any]) -> str:
        """从榜单条目中取出豆瓣 subject id（部分接口放在 uri/url 里）"""
        subject_id = str((item or {}).get('id', '') or '').strip()
        if subject_id:
            return subject_id
        raw = str((item or {}).get('uri', '') or (item or {}).get('url', '') or '')
        match = re.search(r'/(?:movie|tv|subject)/(\d+)', raw)
        return match.group(1) if match else ''

    def fetch_imdb_id(self, subject_id: str) -> Dict[str, Any]:
        """
        抓取单个豆瓣条目的 IMDb ID。

        数据源是豆瓣 App 的「影片信息」H5 页（电影和剧集都走 /movie/ 路径）。
        返回 {imdb_id, status, title}
        status: ok / missing / failed / not_found
        """
        subject_id = str(subject_id or '').strip()
        if not subject_id.isdigit():
            return {'imdb_id': '', 'status': DOUBAN_IMDB_STATUS_NOT_FOUND, 'title': ''}

        result = {'imdb_id': '', 'status': DOUBAN_IMDB_STATUS_FAILED, 'title': ''}
        try:
            session = requests.Session()
            session.headers.update({
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
                ),
                'Referer': 'https://movie.douban.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            })
            response = session.get(_DOUBAN_DESC_URL.format(subject_id=subject_id), timeout=15)
            if response.status_code == 404:
                result['status'] = DOUBAN_IMDB_STATUS_NOT_FOUND
                return result
            if response.status_code != 200:
                logger.warning(f"豆瓣条目 {subject_id} 影片信息请求失败: HTTP {response.status_code}")
                return result

            html = response.text or ''
            title_match = _TITLE_RE.search(html)
            if title_match:
                result['title'] = re.sub(r'\s+', ' ', title_match.group(1)).strip()

            imdb_match = _IMDB_ROW_RE.search(html)
            if imdb_match:
                result['imdb_id'] = imdb_match.group(1)
                result['status'] = DOUBAN_IMDB_STATUS_OK
            else:
                # 页面正常返回但没有 IMDb 行：豆瓣自身就没有这条信息
                result['status'] = DOUBAN_IMDB_STATUS_MISSING
        except Exception as e:
            logger.warning(f"豆瓣条目 {subject_id} 影片信息抓取失败: {e}")
            result['status'] = DOUBAN_IMDB_STATUS_FAILED
        return result

    @staticmethod
    def _cache_ttl(status: str) -> int:
        if status == DOUBAN_IMDB_STATUS_OK:
            return DOUBAN_IMDB_CACHE_TTL_OK
        if status in (DOUBAN_IMDB_STATUS_MISSING, DOUBAN_IMDB_STATUS_NOT_FOUND):
            return DOUBAN_IMDB_CACHE_TTL_MISS
        return DOUBAN_IMDB_CACHE_TTL_FAILED

    def resolve_imdb_ids(self, entries: Iterable[Dict[str, Any]], cal_db,
                         max_fetch: int = 40, concurrency: int = 4,
                         time_budget: float = 12.0) -> Dict[str, Dict[str, Any]]:
        """
        批量解析豆瓣条目的 IMDb ID，优先读缓存，缺的再抓取并写回缓存。

        entries: [{id/subject_id, title, year, is_tv}, ...]
        max_fetch: 本轮最多补抓多少条（其余留到下次刷新）
        time_budget: 本轮补抓的总耗时上限（秒），避免页面加载被拖住
        返回 {subject_id: {imdb_id, status, cached}}
        """
        now = int(time.time())
        normalized = []
        for entry in entries or []:
            subject_id = self._subject_id_of(entry)
            if not subject_id:
                continue
            normalized.append({
                'subject_id': subject_id,
                'title': str((entry or {}).get('title', '') or ''),
                'year': str((entry or {}).get('year', '') or ''),
                'is_tv': bool((entry or {}).get('is_tv')),
            })
        if not normalized:
            return {}

        cached = {}
        if cal_db is not None:
            try:
                cached = cal_db.get_douban_imdb_cache([e['subject_id'] for e in normalized])
            except Exception as e:
                logger.warning(f"读取豆瓣 IMDb 缓存失败: {e}")
                cached = {}

        resolved = {}
        pending = []
        for entry in normalized:
            subject_id = entry['subject_id']
            row = cached.get(subject_id)
            if row:
                status = str(row.get('status', '') or '')
                try:
                    last_updated = int(row.get('last_updated', 0) or 0)
                except (TypeError, ValueError):
                    last_updated = 0
                fresh = last_updated > 0 and (now - last_updated) < self._cache_ttl(status)
                if fresh:
                    resolved[subject_id] = {
                        'imdb_id': str(row.get('imdb_id', '') or ''),
                        'status': status or DOUBAN_IMDB_STATUS_MISSING,
                        'cached': True,
                    }
                    continue
            pending.append(entry)

        if not pending:
            return resolved

        # 只补抓有限条，避免一次榜单刷新把豆瓣请求打爆；
        # 同时限制总耗时，超时未抓完的条目不落缓存，留到下次刷新再试。
        to_fetch = pending[:max(0, int(max_fetch))]
        fetched_rows = []
        if to_fetch:
            results = {}
            deadline = time.time() + max(1.0, float(time_budget))
            workers = max(1, min(int(concurrency or 1), len(to_fetch)))
            executor = None
            try:
                from concurrent.futures import ThreadPoolExecutor
                executor = ThreadPoolExecutor(max_workers=workers)
                future_map = {
                    executor.submit(self.fetch_imdb_id, entry['subject_id']): entry
                    for entry in to_fetch
                }
                for future, entry in future_map.items():
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        future.cancel()
                        continue
                    try:
                        info = future.result(timeout=remaining)
                    except Exception as e:
                        logger.warning(f"豆瓣 IMDb 抓取超时/失败 {entry['subject_id']}: {e}")
                        continue
                    if info:
                        results[entry['subject_id']] = info
            except Exception as e:
                logger.warning(f"豆瓣 IMDb 并发抓取不可用，改为串行: {e}")
                for entry in to_fetch:
                    if time.time() >= deadline:
                        break
                    try:
                        results[entry['subject_id']] = self.fetch_imdb_id(entry['subject_id'])
                    except Exception:
                        continue
            finally:
                if executor is not None:
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        executor.shutdown(wait=False)
                    except Exception:
                        pass

            for entry in to_fetch:
                info = results.get(entry['subject_id'])
                if not info:
                    # 本轮超时/并发中断：不落缓存，下次刷新重试
                    resolved[entry['subject_id']] = {
                        'imdb_id': '', 'status': DOUBAN_IMDB_STATUS_FAILED, 'cached': False,
                    }
                    continue
                status = str(info.get('status', DOUBAN_IMDB_STATUS_FAILED) or DOUBAN_IMDB_STATUS_FAILED)
                imdb_id = str(info.get('imdb_id', '') or '')
                resolved[entry['subject_id']] = {
                    'imdb_id': imdb_id,
                    'status': status,
                    'cached': False,
                }
                # 请求失败的条目按短 TTL 缓存，避免反复打豆瓣；成功后自然覆盖
                fetched_rows.append({
                    'subject_id': entry['subject_id'],
                    'title': entry.get('title') or info.get('title', ''),
                    'year': entry.get('year', ''),
                    'imdb_id': imdb_id,
                    'is_tv': 1 if entry.get('is_tv') else 0,
                    'status': status,
                    'last_updated': now,
                })

        # 超出本轮抓取额度的条目先返回空值，等下次刷新继续补
        for entry in pending[len(to_fetch):]:
            subject_id = entry['subject_id']
            row = cached.get(subject_id) or {}
            resolved[subject_id] = {
                'imdb_id': str(row.get('imdb_id', '') or ''),
                'status': str(row.get('status', '') or DOUBAN_IMDB_STATUS_MISSING),
                'cached': True,
            }

        if fetched_rows and cal_db is not None:
            try:
                cal_db.upsert_douban_imdb_cache(fetched_rows)
            except Exception as e:
                logger.warning(f"写入豆瓣 IMDb 缓存失败: {e}")

        return resolved

    def _process_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理单个影片数据项

        Args:
            item: 原始数据项

        Returns:
            处理后的数据项
        """
        try:
            # 处理图片URL
            pic_data = item.get('pic', {})
            pic_url = ''
            if pic_data:
                # 优先使用normal尺寸的图片
                pic_url = pic_data.get('normal', '') or pic_data.get('large', '')

            # 处理评分数据
            rating_data = item.get('rating', {})
            rating = None
            if rating_data and rating_data.get('value'):
                rating = {'value': rating_data.get('value')}

            # 处理URL - 将douban://协议转换为标准HTTP链接
            original_url = item.get('url', '') or item.get('uri', '')
            processed_url = ''
            if original_url:
                if original_url.startswith('douban://douban.com/'):
                    # 将 douban://douban.com/movie/123 转换为 https://movie.douban.com/subject/123/
                    if '/movie/' in original_url:
                        # 提取ID部分
                        movie_id = original_url.split('/movie/')[-1]
                        processed_url = f'https://movie.douban.com/subject/{movie_id}/'
                    elif '/tv/' in original_url:
                        # 提取ID部分
                        tv_id = original_url.split('/tv/')[-1]
                        processed_url = f'https://movie.douban.com/subject/{tv_id}/'
                    else:
                        processed_url = original_url
                else:
                    processed_url = original_url

            processed = {
                'id': item.get('id', ''),
                'title': item.get('title', ''),
                'year': item.get('year', ''),
                'url': processed_url,
                'pic': {
                    'normal': pic_url
                },
                'rating': rating,
                'card_subtitle': item.get('card_subtitle', '')
            }

            # 确保必要字段存在
            if not processed['title']:
                return None

            return processed

        except Exception:
            return None

    def _get_mock_movie_data(self) -> Dict[str, Any]:
        """获取模拟电影数据"""
        return {
            'notice': "⚠️ 这是模拟数据，非豆瓣实时数据",
            'items': [
                {
                    'id': "1292052",
                    'title': "肖申克的救赎",
                    'rating': {'value': 9.7},
                    'year': "1994",
                    'url': "https://movie.douban.com/subject/1292052/",
                    'pic': {'normal': ""},
                    'card_subtitle': "1994 / 美国 / 剧情 犯罪 / 弗兰克·德拉邦特 / 蒂姆·罗宾斯 摩根·弗里曼"
                },
                {
                    'id': "1291546",
                    'title': "霸王别姬",
                    'rating': {'value': 9.6},
                    'year': "1993",
                    'url': "https://movie.douban.com/subject/1291546/",
                    'pic': {'normal': ""},
                    'card_subtitle': "1993 / 中国大陆 香港 / 剧情 爱情 同性 / 陈凯歌 / 张国荣 张丰毅"
                },
                {
                    'id': "1295644",
                    'title': "阿甘正传",
                    'rating': {'value': 9.5},
                    'year': "1994",
                    'url': "https://movie.douban.com/subject/1295644/",
                    'pic': {'normal': ""},
                    'card_subtitle': "1994 / 美国 / 剧情 爱情 / 罗伯特·泽米吉斯 / 汤姆·汉克斯 罗宾·怀特"
                }
            ],
            'total': 3
        }

    def _get_mock_tv_data(self) -> Dict[str, Any]:
        """获取模拟电视剧数据"""
        return {
            'notice': "⚠️ 这是模拟数据，非豆瓣实时数据",
            'items': [
                {
                    'id': "26794435",
                    'title': "请回答1988",
                    'rating': {'value': 9.7},
                    'year': "2015",
                    'url': "https://movie.douban.com/subject/26794435/",
                    'pic': {'normal': ""},
                    'card_subtitle': "2015 / 韩国 / 剧情 喜剧 家庭 / 申源浩 / 李惠利 朴宝剑"
                },
                {
                    'id': "1309163",
                    'title': "大明王朝1566",
                    'rating': {'value': 9.7},
                    'year': "2007",
                    'url': "https://movie.douban.com/subject/1309163/",
                    'pic': {'normal': ""},
                    'card_subtitle': "2007 / 中国大陆 / 剧情 历史 / 张黎 / 陈宝国 黄志忠"
                },
                {
                    'id': "1309169",
                    'title': "亮剑",
                    'rating': {'value': 9.3},
                    'year': "2005",
                    'url': "https://movie.douban.com/subject/1309169/",
                    'pic': {'normal': ""},
                    'card_subtitle': "2005 / 中国大陆 / 剧情 战争 / 陈健 张前 / 李幼斌 何政军"
                }
            ],
            'total': 3
        }


# 创建全局实例
douban_service = DoubanService()
