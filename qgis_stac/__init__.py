def classFactory(iface):
    from .plugin import StacPlugin

    return StacPlugin(iface)
