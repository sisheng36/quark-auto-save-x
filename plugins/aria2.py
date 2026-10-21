import os
import requests
import sys

# 添加对全局排序函数的引用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from quark_auto_save import sort_file_by_name
    from app.utils.pinyin_sort import get_filename_pinyin_sort_key
except ImportError:
    # 如果无法导入，提供一个简单的排序函数作为替代
    def sort_file_by_name(file):
        if isinstance(file, dict):
            filename = file.get("file_name", "")
            update_time = file.get("updated_at", 0)
        else:
            filename = file
            update_time = 0
        # 简单排序，主要通过文件名进行（使用拼音排序）
        try:
            from pypinyin import lazy_pinyin, Style
            pinyin_list = lazy_pinyin(filename, style=Style.NORMAL, errors='ignore')
            pinyin_sort_key = ''.join(pinyin_list).lower()
        except ImportError:
            pinyin_sort_key = filename.lower()
        # 返回五级排序元组：(日期, 期数, 上中下, 修改时间, 拼音排序)
        return (float('inf'), float('inf'), 0, update_time, pinyin_sort_key)

    def get_filename_pinyin_sort_key(filename):
        try:
            from pypinyin import lazy_pinyin, Style
            pinyin_list = lazy_pinyin(filename, style=Style.NORMAL, errors='ignore')
            return ''.join(pinyin_list).lower()
        except ImportError:
            return filename.lower()


class Aria2:

    default_config = {
        "host_port": "172.17.0.1:6800",  # Aria2 RPC地址
        "secret": "",  # Aria2 RPC 密钥
        "dir": "/downloads",  # 下载目录，需要Aria2有权限访问
    }
    default_task_config = {
        "auto_download": True,  # 是否自动添加下载任务
        "pause": False,  # 添加任务后为暂停状态，不自动开始（手动下载）
        "auto_delete_quark_files": False,  # 是否在添加下载任务后自动删除夸克网盘文件
    }
    is_active = False
    rpc_url = None

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        if kwargs:
            for key, _ in self.default_config.items():
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                else:
                    print(f"{self.plugin_name} 模块缺少必要参数: {key}")
            if self.host_port and self.secret:
                self.rpc_url = f"http://{self.host_port}/jsonrpc"
                if self.get_version():
                    self.is_active = True

    def run(self, task, **kwargs):
        task_config = task.get("addition", {}).get(
            self.plugin_name, self.default_task_config
        )
        if not task_config.get("auto_download"):
            return
        
        account = kwargs.get("account")
        if not account:
            return
            
        # 获取重命名日志，优先使用传入的参数
        rename_logs = kwargs.get("rename_logs", [])
                
        # 从重命名日志中提取文件信息
        renamed_files = {}
        for log in rename_logs:
            if "重命名:" in log and " → " in log:
                # 精确匹配分割
                parts = log.split("重命名:", 1)[1].strip()
                if " → " in parts:
                    old_name, new_name = parts.split(" → ", 1)
                    # 排除失败信息
                    if " 失败，" in new_name:
                        new_name = new_name.split(" 失败，")[0]
                    # 清理空白
                    old_name = old_name.strip()
                    new_name = new_name.strip()
                    renamed_files[old_name] = new_name
        
        # 获取文件树，确定本次需要下载的文件
        current_files_to_download = set()
        savepath = f"/{task['savepath']}".replace('//', '/')
        
        # 从文件树获取文件
        if tree := kwargs.get("tree"):
            file_nodes = [node for node in tree.all_nodes_itr() if not node.data.get("is_dir", True)]
            for node in file_nodes:
                if hasattr(node, 'tag'):
                    # 兼容新旧格式 - 更智能地提取文件名
                    tag_text = node.tag
                    # 处理所有可能的图标前缀
                    for icon in ["🎞️", "📁", "🖼️", "🎵", "📄", "📦", "📝", "💬"]:
                        if tag_text.startswith(icon):
                            # 移除图标并裁剪空格
                            tag_text = tag_text[len(icon):].strip()
                            break
                    filename = tag_text
                    current_files_to_download.add(filename)
        
        # 如果从树中没有获取到文件，使用重命名后的文件
        if not current_files_to_download and renamed_files:
            current_files_to_download = set(renamed_files.values())
        
        # 检查是否获取到了需要下载的文件
        if not current_files_to_download:
            print("📝 Aria2: 未找到需要下载的文件，跳过下载")
            return
            
        # 获取保存路径下所有文件
        if savepath not in account.savepath_fid:
            print(f"📝 Aria2: 保存路径 {savepath} 不存在")
            return
            
        dir_fid = account.savepath_fid[savepath]
        dir_files = account.ls_dir(dir_fid)
        
        # 筛选出当次转存的文件
        file_fids = []
        file_paths = []
        file_info = []  # 存储文件的完整信息，包括ID和路径
        
        for file in dir_files:
            if file.get("dir", False):
                continue  # 跳过目录
                
            file_name = file.get("file_name", "")
            
            # 检查文件是否是当次转存的文件
            is_current_file = False
            
            # 直接匹配文件名或重命名后的文件
            if file_name in current_files_to_download or file_name in renamed_files.values():
                is_current_file = True
            
            if is_current_file:
                file_fids.append(file["fid"])
                file_path = f"{savepath}/{file_name}"
                file_paths.append(file_path)
                # 保存完整信息
                file_info.append({
                    "fid": file["fid"],
                    "path": file_path,
                    "name": file_name
                })
        
        if not file_fids:
            print("📝 Aria2: 未能匹配到需要下载的文件")
            return
        
        # print(f"📝 Aria2: 准备下载 {len(file_fids)} 个文件")
        download_return, cookie = account.download(file_fids)
        
        if not download_return.get("data"):
            print("📝 Aria2: 获取下载链接失败 ❌")
            return
        
        # 准备要下载的文件信息    
        download_items = []
        file_urls = [item["download_url"] for item in download_return["data"]]
        for index, file_url in enumerate(file_urls):
            file_path = file_paths[index]
            local_path = f"{self.dir}{file_paths[index]}"
            
            download_items.append({
                "file_path": file_path,
                "file_url": file_url,
                "local_path": local_path,
                "sort_key": sort_file_by_name(os.path.basename(file_path))
            })
        
        # 使用全局排序函数对文件进行排序
        download_items.sort(key=lambda x: x["sort_key"])
        
        # 记录成功添加到下载队列的文件信息，用于后续删除
        downloaded_files = []
            
        # 按排序后的顺序下载文件
        for item in download_items:
            file_path = item["file_path"]
            file_url = item["file_url"]
            local_path = item["local_path"]
            
            # 检查文件是否已存在
            if os.path.exists(local_path):
                # 如果文件已存在，跳过此文件
                # print(f"📥 Aria2下载: {file_path} (已存在，跳过)")
                continue
            
            print(f"📥 添加 Aria2 下载任务: {file_path} 成功 ✅")
            
            # 确保目录存在
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            aria2_params = [
                [file_url],
                {
                    "header": [
                        f"Cookie: {cookie or account.cookie}",
                        f"User-Agent: {account.USER_AGENT}",
                    ],
                    "out": os.path.basename(local_path),
                    "dir": os.path.dirname(local_path),
                    "pause": task_config.get("pause"),
                },
            ]
            try:
                self.add_uri(aria2_params)
                # 记录成功添加到下载队列的文件信息
                idx = file_paths.index(file_path)
                if idx >= 0 and idx < len(file_info):
                    downloaded_files.append(file_info[idx])
            except Exception as e:
                print(f"📥 添加 Aria2 下载任务失败 ❌ {e}")
        
        # 如果配置了自动删除且有成功添加下载任务的文件，则删除夸克网盘中的文件
        if task_config.get("auto_delete_quark_files") and downloaded_files:
            try:
                # 提取要删除的文件ID
                files_to_delete = []
                for file_data in downloaded_files:
                    # 再次确认文件路径，确保只删除指定目录下的文件
                    if file_data["path"].startswith(savepath):
                        files_to_delete.append(file_data["fid"])
                
                if files_to_delete:
                    account.delete(files_to_delete)
            except Exception as e:
                print(f"📝 Aria2: 删除夸克网盘文件失败 ❌ {e}")
        else:
            if not task_config.get("auto_delete_quark_files"):
                # 未启用自动删除，不需要输出信息
                pass
            elif not downloaded_files:
                # 没有需要删除的文件，不需要输出信息
                pass

    def _make_rpc_request(self, method, params=None):
        """发出 JSON-RPC 请求."""
        jsonrpc_data = {
            "jsonrpc": "2.0",
            "id": "quark-auto-save",
            "method": method,
            "params": params or [],
        }
        if self.secret:
            jsonrpc_data["params"].insert(0, f"token:{self.secret}")
        try:
            response = requests.post(self.rpc_url, json=jsonrpc_data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Aria2 下载: 错误 ❌ {e}")
        return {}

    def get_version(self):
        """检查与 Aria2 的连接."""
        response = self._make_rpc_request("aria2.getVersion")
        if response.get("result"):
            print(f"Aria2 下载: v{response['result']['version']}")
            return True
        else:
            print(f"Aria2 下载: 连接失败 ❌ {response.get('error')}")
            return False

    def add_uri(self, params=None):
        """添加 URI 下载任务."""
        response = self._make_rpc_request("aria2.addUri", params)
        return response.get("result") if response else {}
