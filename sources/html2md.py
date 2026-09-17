import json, re, sys, html
from html.parser import HTMLParser
class P(HTMLParser):
    def __init__(s): super().__init__(); s.out=[]; s.pre=''
    def handle_starttag(s,t,a):
        if t in('h1','h2','h3','h4'): s.out.append('\n\n'+'#'*int(t[1])+' ')
        elif t=='li': s.out.append('\n- ')
        elif t in('p','br','tr','div'): s.out.append('\n')
        elif t in('td','th'): s.out.append(' | ')
    def handle_data(s,d): s.out.append(d)
for i in sys.argv[1:]:
    a=json.load(open(f'sources/raw/netflix-{i}.json',encoding='utf-8'))['article']
    p=P(); p.feed(a['body'])
    t=''.join(p.out); t=re.sub(r'[ \t\xa0]+',' ',t); t=re.sub(r'\n\s*\n+','\n\n',t)
    open(f'sources/raw/netflix-{i}.md','w',encoding='utf-8').write(f"# {a['title']}\n\nsource: {a['html_url']}\nedited_at: {a['edited_at']}\n\n{t}")
