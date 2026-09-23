"""Dependencies for optional agent configuration formats."""


def require_yaml():
    try:
        import yaml
    except ImportError as exc:
        raise ImportError('YAML configuration requires PyYAML. Install it with: pip install "protolink[yaml]"') from exc
    return yaml
