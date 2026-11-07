"""读取同目录 .env，以只读搜索请求验证微信读书连接。仅使用标准库。"""

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


def main():
    env_path = Path(__file__).resolve().with_name('.env')
    key = ''
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            name, sep, value = line.strip().partition('=')
            if sep and name.strip() == 'WEREAD_API_KEY':
                key = value.strip().strip('\"\'')
    key = key or os.environ.get('WEREAD_API_KEY', '').strip()
    if not key:
        print(f'尚未填写密钥，请编辑 {env_path} 中的 WEREAD_API_KEY。')
        return 2
    if not key.startswith('wrk-') or any(c.isspace() for c in key):
        print('密钥格式不正确：应以 wrk- 开头，且不能含空白字符。')
        return 2

    payload = {'api_name': '/store/search', 'keyword': '三体',
               'scope': 10, 'skill_version': '1.0.5'}
    request = urllib.request.Request(
        'https://i.weread.qq.com/api/agent/gateway',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {key}',
                 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f'连接失败：HTTP {exc.code}。请检查密钥有效性及接口权限。')
        return 1
    except (urllib.error.URLError, TimeoutError, OSError):
        print('连接失败：网络、TLS 或超时错误。')
        return 1
    except (ValueError, UnicodeError):
        print('连接失败：接口未返回有效 JSON。')
        return 1

    if not isinstance(result, dict):
        print('连接失败：响应结构不符合预期。')
        return 1
    if 'upgrade_info' in result:
        print('接口要求更新 skill，已停止测试。升级提示：')
        print(json.dumps(result['upgrade_info'], ensure_ascii=False).replace(key, '[已隐藏]'))
        return 3
    if result.get('errcode', 0) not in (0, '0'):
        print('接口返回业务错误：' + str(result['errcode']).replace(key, '[已隐藏]'))
        return 1
    if not isinstance(result.get('results'), list):
        print('接口已响应，但缺少预期的搜索结果，暂不能确认测试通过。')
        print('返回字段：' + ', '.join(result.keys()).replace(key, '[已隐藏]'))
        return 1
    print('测试通过：鉴权成功，微信读书搜索接口正常返回。')
    print(f'搜索“三体”返回 {len(result["results"])} 个结果分组。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
