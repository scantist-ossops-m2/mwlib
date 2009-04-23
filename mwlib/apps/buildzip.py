
# Copyright (c) 2007-2009 PediaPress GmbH
# See README.txt for additional licensing information.

"""mz-zip - installed via setuptools' entry_points"""

import os

def hack(options=None, env=None, podclient=None, **kwargs):
    imagesize = options.imagesize
    metabook = env.metabook
    base_url = env.wiki.api_helper.base_url
    script_extension = env.wiki.api_helper.script_extension
    api_url = "".join([base_url, "api", script_extension])
    output = options.output

    if output:
        fsdir = output+".tmp"
    else:
        fsdir = tempfile.mkdtemp(prefix="nuwiki-")
        

    
    from mwlib import twisted_api
    from twisted.internet import reactor

    def doit():
        api = twisted_api.mwapi(api_url)
        fsout = twisted_api.fsoutput(output)
        fsout.dump_json(metabook=metabook)
        pages = twisted_api.pages_from_metabook(metabook)
        twisted_api.fetcher(api, fsout, pages)
        
    reactor.callLater(0.0, doit)    
    reactor.run()
    
def main():    
    from mwlib.options import OptionParser

    parser = OptionParser()
    parser.add_option("-o", "--output", help="write output to OUTPUT")
    parser.add_option("-p", "--posturl", help="http post to POSTURL (directly)")
    parser.add_option("-g", "--getposturl",
        help='get POST URL from PediaPress.com, open upload page in webbrowser',
        action='store_true',
    )
    parser.add_option('-f', '--fastzipcreator',
        help='Use experimental new fzipcreator code',
        action='store_true',
    )
    options, args = parser.parse_args()
    
    use_help = 'Use --help for usage information.'
    if parser.metabook is None and options.collectionpage is None:
        parser.error('Neither --metabook nor, --collectionpage or arguments specified.\n' + use_help)
    if options.posturl and options.getposturl:
        parser.error('Specify either --posturl or --getposturl.\n' + use_help)
    if not options.posturl and not options.getposturl and not options.output:
        parser.error('Neither --output, nor --posturl or --getposturl specified.\n' + use_help)
    if options.posturl:
        from mwlib.podclient import PODClient
        podclient = PODClient(options.posturl)
    elif options.getposturl:
        import webbrowser
        from mwlib.podclient import podclient_from_serviceurl
        podclient = podclient_from_serviceurl('http://pediapress.com/api/collections/')
        pid = os.fork()
        if not pid:
            try:
                webbrowser.open(podclient.redirecturl)
            finally:
                os._exit(0)
        import time
        time.sleep(1)
        try:
            os.kill(pid, 9)
        except:
            pass
              
    else:
        podclient = None
    
    from mwlib import utils, mwapidb
    
    if options.daemonize:
        utils.daemonize()
    if options.pid_file:
        open(options.pid_file, 'wb').write('%d\n' % os.getpid())

    filename = None
    status = None
    try:
        try:
            env = parser.makewiki()
            print "type:", type(env.wiki)
            
            if isinstance(env.wiki, mwapidb.WikiDB):
                hack(**locals())
            else:    
                from mwlib.status import Status
                if options.fastzipcreator:
                    import mwlib.fzipcreator as zipcreator
                else:
                    from mwlib import zipcreator

                status = Status(podclient=podclient, progress_range=(1, 90))
                status(progress=0)

                filename = zipcreator.make_zip_file(options.output, env,
                    status=status,
                    num_threads=options.num_threads,
                    imagesize=options.imagesize,
                )

                status = Status(podclient=podclient, progress_range=(91, 100))
                if podclient:
                    status(status='uploading', progress=0)
                    podclient.post_zipfile(filename)

                status(status='finished', progress=100)
        except Exception, e:
            if status:
                status(status='error')
            raise
    finally:
        if options.output is None and filename is not None:
            print 'removing %r' % filename
            utils.safe_unlink(filename)
        if options.pid_file:
            utils.safe_unlink(options.pid_file)
