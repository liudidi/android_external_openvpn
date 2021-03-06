# Python module containing general build functions
# for OpenVPN on Windows

import os, re, shutil, stat

autogen = "Automatically generated by OpenVPN Windows build system"

def get_config():
    kv = {}
    parse_version_m4(kv, home_fn('version.m4'))
    parse_settings_in(kv, mod_fn('settings.in'))

    # config fixups
    kv['DDKVER'] = os.path.basename(kv['DDK_PATH'])
    kv['DDKVER_MAJOR'] = re.match(r'^(\d+)\.', kv['DDKVER']).groups()[0]

    if 'VERSION_SUFFIX' in kv:
        kv['PRODUCT_VERSION'] += kv['VERSION_SUFFIX']

    return kv

def mod_fn(fn, src=__file__, real=True):
    p = os.path.join(os.path.dirname(src), os.path.normpath(fn))
    if real:
        p = os.path.realpath(p)
    return p

def home_fn(fn, real=True):
    return mod_fn(os.path.join('..', fn), real=real)

def cd_home():
    os.chdir(os.path.join(os.path.dirname(__file__), '..'))

def system(cmd):
    print "RUN:", cmd
    os.system(cmd)

def parse_version_m4(kv, version_m4):
    r = re.compile(r'^define\((\w+),\[(.*)\]\)$')
    f = open(version_m4)
    for line in f:
        line = line.rstrip()
        m = re.match(r, line)
        if m:
            g = m.groups()
            kv[g[0]] = g[1]
    f.close()

def parse_settings_in(kv, settings_in):
    r = re.compile(r'^!define\s+(\w+)(?:\s+"?(.*?)"?)?$')
    f = open(settings_in)
    for line in f:
        line = line.rstrip()
        m = re.match(r, line)
        if m:
            g = m.groups()
            kv[g[0]] = g[1] or ''
    f.close()

def dict_def(dict, newdefs):
    ret = dict.copy()
    ret.update(newdefs)
    return ret

def build_autodefs(kv, autodefs_in, autodefs_out):
    preprocess(kv,
               in_fn=autodefs_in,
               out_fn=autodefs_out,
               quote_begin='@',
               quote_end='@',
               head_comment='/* %s */\n\n' % autogen)

def preprocess(kv, in_fn, out_fn, quote_begin=None, quote_end=None, if_prefix=None, head_comment=None):
    def repfn(m):
        var, = m.groups()
        return kv.get(var, '')

    re_macro = re_ifdef = None

    if quote_begin and quote_end:
        re_macro = re.compile(r'%s(\w+)%s' % (re.escape(quote_begin), re.escape(quote_end)))

    if if_prefix:
        re_ifdef = re.compile(r'^\s*%sifdef\s+(\w+)\b' % (re.escape(if_prefix),))
        re_else = re.compile(r'^\s*%selse\b' % (re.escape(if_prefix),))
        re_endif = re.compile(r'^\s*%sendif\b' % (re.escape(if_prefix),))

    if_stack = []
    fin = open(in_fn)
    fout = open(out_fn, 'w')
    if head_comment:
        fout.write(head_comment)
    for line in fin:
        if re_ifdef:
            m = re.match(re_ifdef, line)
            if m:
                var, = m.groups()
                if_stack.append(int(var in kv))
                continue
            elif re.match(re_else, line):
                if_stack[-1] ^= 1
                continue
            elif re.match(re_endif, line):
                if_stack.pop()
                continue
        if not if_stack or min(if_stack):
            if re_macro:
                line = re.sub(re_macro, repfn, line)
            fout.write(line)
    assert not if_stack
    fin.close()
    fout.close()

def print_key_values(kv):
    for k, v in sorted(kv.items()):
        print "%s%s%s" % (k, ' '*(32-len(k)), repr(v))

def get_sources(makefile_am):
    c = set()
    h = set()
    f = open(makefile_am)
    state = False
    for line in f:
        line = line.rstrip()
        if line == 'openvpn_SOURCES = \\':
            state = True
        elif not line:
            state = False
        elif state:
            for sf in line.split():
                if sf.endswith('.c'):
                    c.add(sf[:-2])
                elif sf.endswith('.h'):
                    h.add(sf[:-2])
                elif sf == '\\':
                    pass
                else:
                    print >>sys.stderr, "Unrecognized filename:", sf
    f.close()
    return [ sorted(list(s)) for s in (c, h) ]

def output_mak_list(title, srclist, ext):
    ret = "%s =" % (title,)
    for x in srclist:
        ret += " \\\n\t%s.%s" % (x, ext)
    ret += '\n\n'
    return ret

def make_headers_objs(makefile_am):
    c, h = get_sources(makefile_am)
    ret = output_mak_list('HEADERS', h, 'h')
    ret += output_mak_list('OBJS', c, 'obj')
    return ret

def choose_arch(arch_name):
    if arch_name == 'x64':
        return (True,)
    elif arch_name == 'x86':
        return (False,)
    elif arch_name == 'all':
        return (True, False)
    else:
        raise ValueError("architecture ('%s') must be x86, x64, or all" % (arch_name,))

def rm_rf(dir):
    print "REMOVE", dir
    shutil.rmtree(dir, ignore_errors=True)

def mkdir(dir):
    print "MKDIR", dir
    os.mkdir(dir)

def cp_a(src, dest, dest_is_dir=True):
    if dest_is_dir:
        dest = os.path.join(dest, os.path.basename(src))
    print "COPY_DIR %s %s" % (src, dest)
    shutil.copytree(src, dest)

def cp(src, dest, dest_is_dir=True):
    if dest_is_dir:
        dest = os.path.join(dest, os.path.basename(src))
    print "COPY %s %s" % (src, dest)
    shutil.copyfile(src, dest)

def rm_rf(path):
    try:
        shutil.rmtree(path, onerror=onerror)
    except:
        pass

def onerror(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    if not os.access(path, os.W_OK):
        # Is the error an access error ?
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise

def mkdir_silent(dir):
    try:
        os.mkdir(dir)
    except:
        pass

config = get_config()
