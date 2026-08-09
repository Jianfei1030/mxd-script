if __name__ == '__main__':
    import sys
    from config import config
    from ok import OK

    config['debug'] = True
    if '--e2e' in sys.argv:
        config['_e2e_mode'] = True

    ok = OK(config)
    ok.start()
