"""LaTeX output. Every tailored resume is also written as a .tex (Jake's Resume layout, the most common
LaTeX resume on Overleaf) so LaTeX users get an editable source. If a TeX engine is installed
(tectonic, lualatex, xelatex or pdflatex) the 'latex' template compiles the PDF with it.

Users with their own Overleaf CV set profile.apply.latex_template to its main.tex: ApplyTwin then keeps everything
above \\begin{document} (fonts, margins, headings, their \\resumeItem / \\resumeSubheading macros) and writes only the
body, so the tailored PDF looks like the CV they made themselves.
"""
import os
import re
import shutil
import subprocess
import tempfile
from .regions import coursework_label, gpa_label

# what the body needs from any preamble, ours or the user's: symbols that a parser reads as the real character
# (ActualText), links, the text-layer fixes, and a project heading that wraps instead of running off the page
SUPPORT = r"""\usepackage{textcomp}
\usepackage[gen]{eurosym}
\usepackage{accsupp}
\usepackage{calc}
\usepackage{tabularx}
\usepackage{enumitem}
% a symbol drawn by TeX but read by a parser as its Unicode character (pdfLaTeX alone writes the euro sign as "C")
\providecommand{\atsym}[2]{\BeginAccSupp{method=hex,unicode,ActualText=#1}#2\EndAccSupp{}}
\providecommand{\atfs}{\ifdefined\pdffakespace\pdffakespace\fi}
% a project's name, its stack and its date: the name wraps onto a second line rather than running past the margin
\providecommand{\atProjectHeading}[2]{\item
  \begin{tabularx}{0.97\textwidth}[t]{@{}>{\raggedright\arraybackslash}X@{\hspace{10pt}}r@{}}
    \small#1 & #2 \\
  \end{tabularx}\vspace{-7pt}}
"""

PREAMBLE = r"""\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage[usenames,dvipsnames]{color}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{calc}
% every link is underlined: a thin rule drawn just under the link text, so it adds no line height and leaves the text
% (and the spaces around it, see \atfs) exactly as a parser reads it
\newcommand{\lk}[1]{\rlap{\rule[-1.4pt]{\widthof{#1}}{0.4pt}}#1}
\usepackage[english]{babel}
\usepackage{tabularx}
% cmap (before fontenc): a ToUnicode map for the T1 encoding, so the text layer reads real characters even when the T1
% fonts are bitmap EC fonts (no cm-super installed), whose glyphs carry no names: the date dash came out as U+0015
\usepackage{cmap}
\usepackage[T1]{fontenc}
% Bitstream Charter, the serif most Overleaf CVs switch to: outline (Type 1) fonts on every TeX install, so the page is
% crisp and the text layer clean even where Computer Modern falls back to bitmaps
\usepackage{charter}
\ifdefined\pdfgentounicode\input{glyphtounicode}\fi  % pdfTeX only; tectonic/xelatex/lualatex skip it
\pagestyle{empty}
\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}
\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}
\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]
\ifdefined\pdfgentounicode\pdfgentounicode=1\fi
% pdfTeX: real space characters between words, so no parser glues "ms)by". Built-in only: in a user's preamble with icon
% fonts the fake spaces were drawn from the wrong font and shifted the header
\ifdefined\pdfinterwordspaceon\pdfinterwordspaceon\fi
\newcommand{\resumeItem}[1]{\item\small{{#1 \vspace{-2pt}}}}
\newcommand{\resumeSubheading}[4]{\vspace{-2pt}\item
  \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
    \textbf{#1} & #2 \\ \textit{\small#3} & \textit{\small #4} \\
  \end{tabular*}\vspace{-7pt}}
\newcommand{\resumeProjectHeading}[2]{\item
  \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
    \small#1 & #2 \\
  \end{tabular*}\vspace{-7pt}}
\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
""" + SUPPORT

# the user's own preamble gets SUPPORT plus anything a Jake-style body uses that their template may not define
FALLBACK_MACROS = r"""\makeatletter
\@ifpackageloaded{hyperref}{}{\usepackage[hidelinks]{hyperref}}
\makeatother
\providecommand{\lk}[1]{#1}
\ifdefined\pdfgentounicode\input{glyphtounicode}\pdfgentounicode=1\fi
\providecommand{\resumeItem}[1]{\item\small{{#1 \vspace{-2pt}}}}
\providecommand{\resumeSubheading}[4]{\vspace{-2pt}\item
  \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
    \textbf{#1} & #2 \\ \textit{\small#3} & \textit{\small #4} \\
  \end{tabular*}\vspace{-7pt}}
\providecommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\providecommand{\resumeSubHeadingListEnd}{\end{itemize}}
\providecommand{\resumeItemListStart}{\begin{itemize}}
\providecommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
"""

SPECIAL = {'&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
           # '~2,000' means "about": a tilde on the line, not the raised accent \textasciitilde draws in Charter
           '~': r'\atsym{007E}{\ensuremath{\sim}}',
           '^': r'\textasciicircum{}', '\\': r'\textbackslash{}',
           # characters pdfLaTeX can't set from UTF-8 (or sets from a font whose text layer reads wrong): drawn by TeX, read
           # by a parser as the real character ('€73.8k' came out as '¿73.8k', '12×' as '12Ö')
           '€': r'\atsym{20AC}{\euro}', '×': r'\texttimes{}', '±': r'\textpm{}', 'µ': r'\textmu{}', 'μ': r'\textmu{}',
           '≥': r'\atsym{2265}{\ensuremath{\geq}}', '≤': r'\atsym{2264}{\ensuremath{\leq}}', '≠': r'\atsym{2260}{\ensuremath{\neq}}',
           '≈': r'\atsym{2248}{\ensuremath{\approx}}', '∼': r'\atsym{223C}{\ensuremath{\sim}}', '→': r'\atsym{2192}{\ensuremath{\rightarrow}}',
           '←': r'\atsym{2190}{\ensuremath{\leftarrow}}', '↔': r'\atsym{2194}{\ensuremath{\leftrightarrow}}',
           '⇒': r'\atsym{21D2}{\ensuremath{\Rightarrow}}', '√': r'\atsym{221A}{\ensuremath{\surd}}', '∞': r'\atsym{221E}{\ensuremath{\infty}}',
           '²': r'\atsym{00B2}{\textsuperscript{2}}', '³': r'\atsym{00B3}{\textsuperscript{3}}', '−': r'\atsym{2212}{\ensuremath{-}}'}
for _n, _c in (('alpha', 'α'), ('beta', 'β'), ('gamma', 'γ'), ('delta', 'δ'), ('epsilon', 'ε'), ('theta', 'θ'), ('lambda', 'λ'),
               ('pi', 'π'), ('rho', 'ρ'), ('sigma', 'σ'), ('tau', 'τ'), ('phi', 'φ'), ('omega', 'ω'), ('Delta', 'Δ'), ('Sigma', 'Σ')):
    SPECIAL[_c] = r'\atsym{%04X}{\ensuremath{\%s}}' % (ord(_c), _n)


def url(u):
    """A link target that survives LaTeX, including inside table rows (& is a column separator there)."""
    return (u or '').replace('\\', '/').replace('%', r'\%').replace('#', r'\#').replace('&', r'\&').replace('{', '').replace('}', '')


def esc(s):
    # f{}i: an empty group stops TeX forming the ff/fi/fl/ffi ligatures, which XeTeX (tectonic) writes into the PDF as
    # single U+FB0x characters, so 'efficient' wouldn't match a parser's keyword search
    # A{}w, T{}o: the same empty group stops the big kerns after these capitals, which PDF text extractors read as a word
    # gap ("PyT orch", "W orkshop", "A w ards"), so a keyword or a section heading went missing
    # (only on the plain text between escapes: a command such as \atsym{20AC} must come through untouched)
    def plain(t):
        t = re.sub(r"(?<![\w.,)])'(?=\w)", '`', t)   # an opening quote ('Research to Trade') is `, else TeX sets ’
        t = re.sub(r'-(?=-)', '-{}', t)   # '--' and '---' would be TeX's en and em dash: the user never wants either
        return re.sub(r'([AFKLPTVWY])(?=[A-Za-z])', r'\1{}', re.sub(r'f(?=[fil])', 'f{}', t))
    out, run = [], []
    for c in s or '':
        if c in SPECIAL:
            out += [plain(''.join(run)), SPECIAL[c]]
            run = []
        else:
            run.append(c)
    return ''.join(out) + plain(''.join(run))


def heading(s):
    """A section title for the small-caps heading: an empty group between every two letters, because in small caps every
    pair kerns like capitals ("Aw ards" in the text layer) and a parser then can't find the heading."""
    s = s or ''
    return ''.join(esc(c) + ('{}' if c.isalpha() and n.isalpha() else '') for c, n in zip(s, s[1:] + ' '))


def tex(s):
    """light markdown (**bold**, [text](url)) -> LaTeX"""
    out, i = [], 0
    for m in re.finditer(r'\[([^\]]+)\]\(([^)\s]+)\)', s or ''):
        out.append(_bold(esc(s[i:m.start()])))
        out.append(r'\href{%s}{\lk{%s}}' % (url(m.group(2)), _bold(esc(m.group(1)))))
        i = m.end()
    out.append(_bold(esc((s or '')[i:])))
    return ''.join(out)


def _bold(s):
    return re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', s)


def dates(e):
    a, b = e.get('start', ''), e.get('end', '')
    return esc(f'{a} - {b}' if a and b else (b or a))


def user_template(path=None):
    """The preamble of the user's own LaTeX CV (profile.apply.latex_template, a main.tex from Overleaf), or None."""
    if path is None:
        try:
            from . import store
            path = (store.profile().get('apply') or {}).get('latex_template') or ''
        except Exception:
            path = ''
    path = os.path.expanduser(os.path.expandvars(str(path or '').strip().strip('"')))
    if not path or not os.path.isfile(path):
        return None
    try:
        src = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return None
    i = src.find(r'\begin{document}')
    pre = src[:i] if i > 0 else ''
    return pre if re.search(r'\\documentclass', pre) else None


def _own_preamble(pre, k, a4):
    """The user's preamble, sized and papered for this page, with what ApplyTwin's body and a clean text layer need."""
    m = re.search(r'\\documentclass(\[[^\]]*\])?\{([^}]*)\}', pre)
    opts = [o.strip() for o in (m.group(1) or '[]')[1:-1].split(',') if o.strip()]
    opts = [o for o in opts if o not in ('letterpaper', 'a4paper')] + ['a4paper' if a4 else 'letterpaper']
    if k < 0.99:   # one size smaller to fit the page, as the built-in template does (extarticle also has 9pt)
        steps = ['12pt', '11pt', '10pt'] + (['9pt'] if m.group(2).strip().startswith('ext') else [])
        opts = [steps[min(steps.index(o) + 1, len(steps) - 1)] if o in steps else o for o in opts]
    cls = r'\documentclass[%s]{%s}' % (','.join(opts), m.group(2))
    pre = pre[:m.start()] + cls + ('' if 'cmap' in pre else '\n\\usepackage{cmap}') + pre[m.end():]
    pre = pre.rstrip() + '\n% ---- added by ApplyTwin: links, symbols and a text layer every application system can read ----\n'
    pre += SUPPORT + FALLBACK_MACROS
    if k < 0.93:
        pre += '\\setlist{itemsep=-1pt}\n'
    return pre


ICONS = (('phone', 'phone'), ('email', 'envelope'), ('location', 'map-marker-alt'), ('status', None))


def _link_icon(u):
    u = (u or '').lower()
    return 'github' if 'github.' in u else 'linkedin' if 'linkedin.' in u else 'gitlab' if 'gitlab.' in u else 'globe'


def build_tex(r, k=1.0, template=None):
    """The resume as LaTeX. template: the user's own preamble (see user_template), read from the profile when not given;
    '' forces the built-in one."""
    from .render import clean
    from .regions import a4
    r = clean(r)   # pasted ligature glyphs, soft hyphens and zero-width spaces out of the text
    own = user_template() if template is None else (user_template(template) if template else None)
    icons = bool(own and re.search(r'\\usepackage(\[[^\]]*\])?\{fontawesome5?\}', own))
    b = r.get('basics', {})

    def item(kind, text):
        return (r'\mbox{\faIcon{%s}}\ ' % kind if icons and kind else '') + text
    contact = []
    for key, icon in ICONS:
        if b.get(key):
            x = esc(b[key])
            if key == 'email':
                x = r'\href{mailto:%s}{\lk{%s}}' % (url(b[key]), x)
            contact.append(item(icon, x))
    for l in b.get('links', []):
        label = l.get('label') or re.sub(r'^https?://(www\.)?', '', l.get('url', '')).rstrip('/')
        contact.append(item(_link_icon(l.get('url') or label), r'\href{%s}{\lk{%s}}' % (url(l.get('url', '')), esc(label))))
    body = [r'\begin{center}', r'\textbf{\Huge \scshape %s} \\ \vspace{%s}' % (esc(b.get('name', '')), '8pt' if own else '1pt')]
    if b.get('headline') and not own:   # the user's own header has no tag line: theirs is name and contact only
        body.append(r'\small %s \\ \vspace{1pt}' % r' $\cdot$ '.join(tex(h) for h in b['headline']))
    # the user's header is normal size for a few items; more than three set small, so the line doesn't wrap
    body += [('' if own and len(contact) <= 3 else r'\small ') + r' $|$ '.join(contact), r'\end{center}']
    for sec in r.get('order') or []:
        data = r.get(sec)
        if not data:
            continue
        title = (r.get('titles') or {}).get(sec) or {'education': 'Education', 'experience': 'Experience', 'projects': 'Projects',
                                                     'research': 'Research and Publications', 'leadership': 'Leadership',
                                                     'volunteering': 'Volunteer Experience', 'skills': 'Skills',
                                                     'certifications': 'Licenses and Certifications', 'awards': 'Awards'}.get(sec, sec.title())
        body.append(r'\section{%s}' % heading(title))
        if sec == 'education':
            body.append(r'\resumeSubHeadingListStart')
            for e in data:
                from .render import degree_line
                deg = '; '.join(x for x in (degree_line(e), e.get('minor') and 'Minor in ' + e['minor'],
                                            e.get('gpa') and f"{gpa_label(e)}: {e['gpa']}") if x)
                body.append(r'\resumeSubheading{%s}{%s}{%s}{%s}' % (esc(e.get('school')), esc(e.get('location')), esc(deg), dates(e)))
                # honors share one line (as in the HTML templates) instead of one bullet each
                extra = ([r' $\cdot$ '.join(tex(h) for h in e['honors'])] if e.get('honors') else []) + \
                        ([r'\textbf{%s:} ' % esc(coursework_label(r)) + esc(', '.join(e['coursework']))] if e.get('coursework') else [])
                if extra:
                    body += [r'\resumeItemListStart'] + [r'\resumeItem{%s}' % x for x in extra] + [r'\resumeItemListEnd']
            body.append(r'\resumeSubHeadingListEnd')
        elif sec in ('experience', 'leadership', 'volunteering'):
            body.append(r'\resumeSubHeadingListStart')
            for e in data:
                # Jake's order: the role in bold on the first line, the organisation in italics under it
                org = tex(e.get('org', '')) if not e.get('url') else r'\href{%s}{\lk{%s}}' % (url(e['url']), tex(e.get('org', '')))
                role = tex(e.get('title', '')) + ((r'\textmd{ $|$ %s}' % esc(', '.join(e['stack']))) if e.get('stack') else '')
                body.append(r'\resumeSubheading{%s}{%s}{%s}{%s}' % (role or org, dates(e), org if role else '', esc(e.get('location', ''))))
                if e.get('bullets'):
                    body += [r'\resumeItemListStart'] + [r'\resumeItem{%s}' % tex(x) for x in e['bullets']] + [r'\resumeItemListEnd']
            body.append(r'\resumeSubHeadingListEnd')
        elif sec == 'projects':
            body.append(r'\resumeSubHeadingListStart')
            for p in data:
                # "**Name** (stack, kind)": a name that carries its own brackets keeps them, unbolded; otherwise the first
                # few tools. The tagline and the full tech list stay in the vault: on the page they ran to four lines.
                name = (p.get('name') or '').strip()
                m = re.match(r'^(.*\S)\s*(\([^()]*\))$', name)
                nm, paren = (m.group(1), m.group(2)) if m else (name, '(%s)' % ', '.join(p['tech'][:4]) if p.get('tech') else '')
                nm = r'\textbf{%s}' % tex(nm)
                if p.get('url'):
                    nm = r'\href{%s}{\lk{%s}}' % (url(p['url']), nm)
                body.append(r'\atProjectHeading{%s%s}{%s}' % (nm, (' ' + esc(paren)) if paren else '', esc(p.get('date', ''))))
                if p.get('bullets'):
                    body += [r'\resumeItemListStart'] + [r'\resumeItem{%s}' % tex(x) for x in p['bullets']] + [r'\resumeItemListEnd']
            body.append(r'\resumeSubHeadingListEnd')
        elif sec == 'skills':
            body.append(r'\begin{itemize}[leftmargin=0.15in, label={}]\small{\item{')
            body.append(r' \\ '.join(r'\textbf{%s}{: %s}' % (esc(s.get('label', '')), esc(', '.join(s.get('items', [])))) for s in data))
            body.append(r'}}\end{itemize}')
        else:  # research, awards, certifications: bullets lined up with the experience bullets, same size and spacing
            body.append(r'\begin{itemize}[leftmargin=\dimexpr0.15in+\leftmarginii\relax, label=\labelitemii, topsep=0pt]')
            for x in data:
                if isinstance(x, str):
                    body.append(r'\resumeItem{%s}' % tex(x))
                else:
                    t = tex(x.get('title', ''))
                    if x.get('url'):
                        t = r'\href{%s}{\lk{%s}}' % (url(x['url']), t)
                    body.append(r'\resumeItem{%s%s%s}' % ((tex(x['role']) + ': ') if x.get('role') else '', t,
                                                          (r'. \textbf{%s}' % tex(x['venue'])) if x.get('venue') else ''))
            body.append(r'\end{itemize}\vspace{-4pt}')
    # \small and the headings are relative to the class size, so shrink by changing the class size (11pt -> 10pt), and at
    # the last step also tighten the space between items
    # A4 by default; Letter only for US and Canadian jobs (regions.conventions)
    if own:
        pre = _own_preamble(own, k, a4(r.get('paper')))
    else:
        pre = PREAMBLE if k >= 0.99 else PREAMBLE.replace('[letterpaper,11pt]', '[letterpaper,10pt]')
        if a4(r.get('paper')):
            pre = pre.replace('letterpaper', 'a4paper')
        if k < 0.93:
            pre += '\n\\setlist{itemsep=-1pt}\n'
    doc = '\n'.join(body)
    # pdfTeX drops the word space next to a boxed underline from the text layer ("prototypeand"): put a real space
    # character back on each side of a link that sits between words
    # (only for the built-in underline: the user's plain links need no help, and there the fake space shifted the text)
    if not own:
        lk = r'\\href\{[^{}]*\}\{\\lk\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}\}'
        doc = re.sub(r'(?<= )(' + lk + ')', r'\\atfs{}\1', doc)
        doc = re.sub('(' + lk + r')(?= )', r'\1\\atfs{}', doc)
    return pre + '\n\\begin{document}\n' + doc + '\n\\end{document}\n'


# pdfLaTeX first, as on Overleaf: with glyphtounicode and \pdfinterwordspaceon its text layer has real spaces and plain
# letters, which every parser reads; tectonic (XeTeX) next, then LuaLaTeX and XeLaTeX
ENGINES = ('pdflatex', 'tectonic', 'lualatex', 'xelatex')


def _tex_dirs():
    """Where TeX installs put their programs when PATH doesn't say (the app starts at login, before MiKTeX or TeX Live
    may have been installed, and keeps that PATH)."""
    if os.name != 'nt':
        return ['/Library/TeX/texbin', '/opt/homebrew/bin', '/usr/local/bin']
    import glob
    from .store import refresh_path
    refresh_path()
    la, pf = os.environ.get('LOCALAPPDATA', ''), os.environ.get('ProgramFiles', r'C:\Program Files')
    return ([os.path.join(la, 'Programs', 'MiKTeX', 'miktex', 'bin', 'x64'), os.path.join(pf, 'MiKTeX', 'miktex', 'bin', 'x64')]
            + sorted(glob.glob(r'C:\texlive\*\bin\windows') + glob.glob(r'C:\texlive\*\bin\win64'), reverse=True)
            + [os.path.join(la, 'Programs', 'tectonic'), os.path.join(os.path.expanduser('~'), '.cargo', 'bin')])


def engines():
    out, dirs = [], None
    for e in ENGINES:
        p = shutil.which(e)
        if not p:
            dirs = dirs if dirs is not None else _tex_dirs()
            p = next((shutil.which(e, path=d) for d in dirs if os.path.isdir(d) and shutil.which(e, path=d)), None)
        if p:
            out.append((e, p))
    return out


def engine():
    return (engines() or [(None, None)])[0]


def compile_tex(src, out_pdf):
    from .store import NOWIN   # no console window flashing up per compile on Windows
    found = engines()
    if not found:
        raise RuntimeError('No LaTeX engine found (install tectonic or TeX Live, or pick another template)')
    for name, exe in found:   # a minimal TeX install can miss a package one engine needs: try the next engine
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, 'resume.tex')
            open(f, 'w', encoding='utf-8').write(src)
            cmd = [exe, f] if name == 'tectonic' else [exe, '-interaction=nonstopmode', '-halt-on-error', 'resume.tex']
            if name != 'tectonic' and 'miktex' in exe.lower():
                cmd.insert(1, '--enable-installer')   # install a missing package quietly, not with a dialog nobody sees
            try:   # one pass: there are no cross-references, so a second run changes nothing
                rc = subprocess.run(cmd, cwd=td, capture_output=True, timeout=180, **NOWIN).returncode
            except (OSError, subprocess.SubprocessError):
                continue
            pdf = os.path.join(td, 'resume.pdf')
            if rc == 0 and os.path.exists(pdf) and os.path.getsize(pdf) > 0:
                os.makedirs(os.path.dirname(os.path.abspath(out_pdf)), exist_ok=True)
                shutil.copy(pdf, out_pdf)
                return out_pdf
    raise RuntimeError('LaTeX failed to compile')
