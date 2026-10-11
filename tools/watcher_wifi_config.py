"""Validate the optional, private Watcher Wi-Fi header before compilation.

This module never prints or returns credentials and has no import-time effects.
The header intentionally supports three literal declarations, not arbitrary C++.
"""
from pathlib import Path
import re

BOARD = Path('main/boards/sensecap-watcher-gesture')
_LITERAL = r'"(?:[^"\\\r\n]|\\[^\r\n])*"'
_DECLARATION = re.compile(
    r'(?:constexpr\s+(?:const\s+)?|const\s+)bool\s+WATCHER_SOURCE_WIFI_ENABLED\s*=\s*(?P<enabled>true|false)\s*;'
    r'|(?:constexpr\s+)?const\s+char\s*\*\s*(?P<name>WIFI_SSID|WIFI_PASSWORD)\s*=\s*(?P<literal>' + _LITERAL + r')\s*;'
)
_COMMENTS = re.compile(_LITERAL + r'|//[^\r\n]*|/\*[\s\S]*?\*/')


def _fail(path, reason):
    # 只返回配置位置和错误类别；异常也不携带源码行或实际凭据。
    raise ValueError(f'{path}: {reason}')


def _literal_bytes(token, path):
    output = []
    content = token[1:-1]
    index = 0
    escapes = {'"': '"', '\\': '\\', 'n': '\n', 'r': '\r', 't': '\t'}
    while index < len(content):
        char = content[index]
        if char == '\\':
            index += 1
            if index >= len(content) or content[index] not in escapes:
                _fail(path, 'unsupported string escape; use literal UTF-8, \\" or \\\\')
            char = escapes[content[index]]
        output.append(char)
        index += 1
    try:
        return ''.join(output).encode('utf-8')
    except UnicodeError:
        _fail(path, 'invalid UTF-8 string')


def validate_source_wifi_config(project):
    """Return non-secret metadata; enabled invalid settings raise ValueError."""
    path = Path(project) / BOARD / 'wifi_settings.h'
    if path.is_symlink():
        _fail(path, 'private header must be a regular file, not a symlink')
    if not path.exists():
        return {'present': False, 'enabled': False}
    if not path.is_file():
        _fail(path, 'private header must be a regular file')
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        _fail(path, 'private header cannot be read as UTF-8')
    # 保留字符串中的 // 与引号；删除真正的 C++ 注释后只接受示例中的声明。
    text = _COMMENTS.sub(lambda match: match.group() if match.group().startswith('"') else ' ', text)
    text = re.sub(r'^\s*#pragma\s+once\s*$', '', text, flags=re.MULTILINE)
    settings = {}
    for match in _DECLARATION.finditer(text):
        name = match.group('name') or 'WATCHER_SOURCE_WIFI_ENABLED'
        if name in settings:
            _fail(path, 'duplicate configuration declaration')
        settings[name] = match.group('enabled') if match.group('enabled') else _literal_bytes(match.group('literal'), path)
    if _DECLARATION.sub('', text).strip() or set(settings) != {'WATCHER_SOURCE_WIFI_ENABLED', 'WIFI_SSID', 'WIFI_PASSWORD'}:
        _fail(path, 'use the three literal declarations in wifi_settings.example.h')
    enabled = settings['WATCHER_SOURCE_WIFI_ENABLED'] == 'true'
    if enabled:
        ssid, password = settings['WIFI_SSID'], settings['WIFI_PASSWORD']
        if not 1 <= len(ssid) <= 32:
            _fail(path, 'SSID must contain 1–32 UTF-8 bytes')
        if not 8 <= len(password) <= 63:
            _fail(path, 'password must contain 8–63 UTF-8 bytes')
        if ssid.startswith(b'YOUR_') or password.startswith(b'YOUR_'):
            _fail(path, 'replace placeholders before enabling source Wi-Fi')
        if any(byte < 32 or byte == 127 for byte in ssid + password):
            _fail(path, 'network strings cannot contain control characters')
    return {'present': True, 'enabled': enabled}
