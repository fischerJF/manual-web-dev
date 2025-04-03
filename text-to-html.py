import re
import sys
from pathlib import Path

# Dicionários globais para armazenar labels e contadores
ref_labels = {}
refs_counter = {
    'Capítulo': 1, 'Seção': 1, 'Subseção': 1, 'Subsubseção': 1,
    'Código': 1, 'Figura': 1, 'Tabela': 1
}

def parse_labels(content: str) -> None:
    """
    Procura e associa os rótulos (labels) aos seus respectivos comandos e números.
    Atualiza o dicionário global ref_labels.
    """
    label_regex = re.compile(
        r'\\label\{(.*?)\}|label\s*=\s*(.*?)(?:,|\])|label\s*=\s*\{(.*?)\}'
    )
    for label in re.finditer(label_regex, content):
        label_name = label.group(1) or label.group(2) or label.group(3)
        commands_before = re.findall(r'\\(\w+)(?:\[(.*?)\])?\{(.*?)\}', content[:label.start()])
        label_type = None
        comando = None
        for command in reversed(commands_before):
            comando_nome = command[0]
            if comando_nome == 'chapter':
                label_type = 'Capítulo'
            elif comando_nome == 'section':
                label_type = 'Seção'
            elif comando_nome == 'subsection':
                label_type = 'Subseção'
            elif comando_nome == 'subsubsection':
                label_type = 'Subsubseção'
            elif comando_nome == 'begin' and command[2] == 'lstlisting':
                label_type = 'Código'
                comando = 'codigo'
            elif comando_nome == 'begin' and command[2] == 'figure':
                label_type = 'Figura'
                comando = 'figura'
            elif comando_nome == 'begin' and command[2] == 'table':
                label_type = 'Tabela'
            if label_type:
                if not comando:
                    comando = comando_nome
                break
        if label_type:
            ref_labels[label_name] = {
                'type': label_type,
                'command': comando,
                'counter': refs_counter[label_type],
                'text': f"{label_type} {refs_counter[label_type]}"
            }
            refs_counter[label_type] += 1

def remove_latex_commands(content: str) -> str:
    """
    Remove comentários e comandos LaTeX desnecessários (exceto os já convertidos).
    """
    content = re.sub(r'(?m)^%.*$', '', content)
    content = re.sub(r'\\newpage', '', content)
    content = re.sub(r'\\#', '#', content)
    content = re.sub(r'\\label\{.*?\}', '', content)
    content = re.sub(r'\\Needspace\{.*?\}', '', content)
    # A linha abaixo foi comentada para evitar converter as tags HTML geradas:
    return content

def replace_references(content: str) -> str:
    """
    Substitui comandos \ref e \autoref por links HTML.
    """
    content = re.sub(
        r'(?:~|)\\ref\{(.*?)\}',
        lambda m: (f' <a href="#{ref_labels[m.group(1)]["command"]}-{ref_labels[m.group(1)]["counter"]}">'
                   f'{ref_labels[m.group(1)]["counter"]}</a>') if m.group(1) in ref_labels else "?",
        content
    )
    content = re.sub(
        r'(?:~|)\\autoref\{(.*?)\}',
        lambda m: (f' <a href="#{ref_labels[m.group(1)]["command"]}-{ref_labels[m.group(1)]["counter"]}">'
                   f'{ref_labels[m.group(1)]["text"]}</a>') if m.group(1) in ref_labels else "?",
        content
    )
    return content

def parse_lstlisting_options(options: str) -> dict:
    """
    Extrai as opções do ambiente lstlisting de forma robusta, permitindo que os valores
    contenham comandos LaTeX com chaves aninhadas, como \textit{JavaScript}.
    As opções devem estar separadas por vírgula.
    """
    opts = {}
    key = ""
    value = ""
    state = "key"  # "key" ou "value"
    brace_depth = 0
    i = 0

    while i < len(options):
        ch = options[i]
        if state == "key":
            if ch == "=":
                state = "value"
            else:
                key += ch
        elif state == "value":
            if ch == '{':
                brace_depth += 1
                value += ch
            elif ch == '}':
                if brace_depth > 0:
                    brace_depth -= 1
                value += ch
            elif ch == ',' and brace_depth == 0:
                opts[key.strip()] = value.strip()
                key = ""
                value = ""
                state = "key"
            else:
                value += ch
        i += 1

    if key.strip():
        opts[key.strip()] = value.strip()
    return opts


def code_block_replacement(match: re.Match) -> str:
    """
    Substitui um bloco lstlisting por um <pre> com o código e uma legenda separada.
    """
    options_str = match.group('options')
    code_content = match.group('code')
    opts = parse_lstlisting_options(options_str)
    
    caption = opts.get('caption', '').rstrip(',.')
    label = opts.get('label', '')
    
    if label:
        if label not in ref_labels:
            ref_labels[label] = {
                'type': 'Código',
                'command': 'codigo',
                'counter': refs_counter['Código'],
                'text': f"Código {refs_counter['Código']}"
            }
            refs_counter['Código'] += 1
        counter = ref_labels[label]["counter"]
        html = (
            f'<pre id="codigo-{counter}" class="bloco-codigo">{code_content.strip()}</pre>\n'
            f'<label class="legenda">{ref_labels[label]["type"]} {counter}'
        )
        if caption:
            html += f' - {caption}'
        html += '.</label>'
    else:
        html = f'<pre class="bloco-codigo">{code_content.strip()}</pre>'
    return html

def replace_code_blocks(content: str) -> str:
    """
    Captura e substitui os blocos lstlisting por HTML.
    """
    pattern = r'\\begin\{lstlisting\}\[(?P<options>[^\]]*)\](?P<code>.*?)\\end\{lstlisting\}'
    return re.sub(pattern, code_block_replacement, content, flags=re.DOTALL)

def replace_figures(content: str) -> str:
    """
    Converte ambientes figure para HTML.
    Extrai o caminho da imagem (aceitando argumentos opcionais),
    converte a extensão para .png, extrai a legenda e o label,
    e gera a tag <img> com a legenda.
    """
    def figure_replacement(match: re.Match) -> str:
        figure_block = match.group(1)
        figure_block = re.sub(r'\\centering', '', figure_block)
        img_match = re.search(r'\\includegraphics(?:\[[^\]]*\])?\s*\{(.*?)\}', figure_block)
        if not img_match:
            return ""
        img_path = img_match.group(1).strip()
        if '.' in img_path:
            base = img_path.rsplit('.', 1)[0]
            base = base.rsplit('/', 1)[-1]
            default_dir = "figures/"
            img_src = default_dir + base + ".png"
        else:
            img_src = img_path + ".png"
        caption_match = re.search(r'\\caption\s*\{(.*?)\}', figure_block, re.DOTALL)
        caption = caption_match.group(1).strip() if caption_match else ""
        label_match = re.search(r'\\label\s*\{(.*?)\}', figure_block)
        label = label_match.group(1).strip() if label_match else ""
        if label:
            if label not in ref_labels:
                ref_labels[label] = {
                    'type': 'Figura',
                    'command': 'figura',
                    'counter': refs_counter['Figura'],
                    'text': f"Figura {refs_counter['Figura']}"
                }
                refs_counter['Figura'] += 1
            counter = ref_labels[label]["counter"]
            html = (
                '<div class="container">\n'
                f'<img class="figura" id="figura-{counter}" src="{img_src}" />\n'
                f'<label class="legenda">{ref_labels[label]["type"]} {counter}\n'
            )
            if caption:
                html += f' - {caption}'
            html += '.</label></div>'
        else:
            html = f'<img class="figura" src="{img_src}" />'
        return html

    pattern = r'\\begin\{figure\}(.*?)\\end\{figure\}'
    return re.sub(pattern, figure_replacement, content, flags=re.DOTALL)

def replace_tables(content: str) -> str:
    """
    Converte ambientes table para HTML.
    Extrai o ambiente tabular, remove comandos desnecessários
    (como \centering, \caption e \label) que não fazem parte do conteúdo
    da tabela, processa suas linhas e células, adiciona legenda e label,
    e gera uma tabela HTML.
    """
    def table_replacement(match: re.Match) -> str:
        table_block = match.group(1)
        
        # Remove \centering para evitar que apareça na tabela
        table_block = re.sub(r'\\centering\s*', '', table_block)
        
        # Captura a legenda e processa os comandos de formatação nela
        caption_match = re.search(r'\\caption\s*\{(.*?)\}', table_block, re.DOTALL)
        caption = caption_match.group(1).strip() if caption_match else ""
        caption = replace_formatting_commands(caption) if caption else caption
        
        # Captura o label
        label_match = re.search(r'\\label\s*\{(.*?)\}', table_block)
        label = label_match.group(1).strip() if label_match else ""
        
        # Remove os comandos de caption e label do bloco
        table_block = re.sub(r'\\caption\s*\{.*?\}', '', table_block, flags=re.DOTALL)
        table_block = re.sub(r'\\label\s*\{.*?\}', '', table_block)

        # Agora, captura somente o conteúdo após a especificação de colunas
        # Exemplo: \begin{tabular}{|p{9cm}|} ... \end{tabular}
        tabular_pattern = r'\\begin\{tabular\}\{[^\}]*\}(?P<tabular_content>.*?)\\end\{tabular\}'
        tabular_match = re.search(tabular_pattern, table_block, re.DOTALL)
        if not tabular_match:
            # Se não achar um ambiente tabular, não gera nada
            return ""
        
        # Pega somente o que interessa, sem a parte {|p{9cm}|}
        tabular_content = tabular_match.group("tabular_content")
        
        # Remove \hline e quebras de linha indesejadas
        tabular_content = re.sub(r'\\hline', '', tabular_content)
        
        # Divide em linhas pela quebra de linha '\\'
        rows = re.split(r'\\\\', tabular_content)
        
        table_body = '<tbody>'
        for row in rows:
            row = row.strip()
            if not row:
                continue
            # Separa as células e remove espaços em branco
            cells = [cell.strip() for cell in row.split('&')]
            table_body += '<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>'
        table_body += '</tbody>'
        
        # Monta o HTML da tabela
        table_html = f'<table class="tabela">{table_body}</table>'
        
        # Se existir label, registra e insere o id na tabela
        if label:
            if label not in ref_labels:
                ref_labels[label] = {
                    'type': 'Tabela',
                    'command': 'tabela',
                    'counter': refs_counter['Tabela'],
                    'text': f"Tabela {refs_counter['Tabela']}"
                }
                refs_counter['Tabela'] += 1
            counter = ref_labels[label]["counter"]
            table_html = table_html.replace('<table ', f'<table id="tabela-{counter}" ', 1)
            html = (
                '<div class="container">\n'
                f'{table_html}\n'
                f'<label class="legenda">{ref_labels[label]["type"]} {counter}'
            )
            if caption:
                html += f' - {caption}'
            html += '.</label></div>'
        else:
            html = table_html
        return html

    pattern = r'\\begin\{table\}(.*?)\\end\{table\}'
    return re.sub(pattern, table_replacement, content, flags=re.DOTALL)


def replace_sections(content: str, chapter_number: int) -> str:
    """
    Converte os comandos \section e \subsection para tags HTML numeradas.
    """
    section_counter = 1
    subsection_counter = None
    last_section_number = 0

    def section_subsection(match: re.Match) -> str:
        nonlocal section_counter, subsection_counter, last_section_number
        comando = match.group(1)
        titulo = match.group(2)
        if comando == 'section':
            result = f'<h2 id="section-{section_counter}" class="secao">{chapter_number}.{section_counter}. {titulo}</h2>'
            last_section_number = section_counter
            section_counter += 1
            subsection_counter = 1
        elif comando == 'subsection':
            result = f'<h3 class="subsecao">{chapter_number}.{last_section_number}.{subsection_counter} {titulo}</h3>'
            subsection_counter += 1
        return result

    return re.sub(r'\\(section|subsection)\{(.*?)\}', section_subsection, content)

def extract_balanced(text: str, start: int) -> (str, int):
    """
    A partir da posição 'start' (após a abertura '{'), retorna o conteúdo com chaves balanceadas
    e a posição do delimitador de fechamento correspondente.
    """
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
        i += 1
    return text[start:i-1], i - 1

def replace_formatting_commands(text: str) -> str:
    """
    Processa os comandos de formatação (ex: \textbf, \textit, \texttt)
    de modo que comandos aninhados sejam interpretados corretamente.
    """
    commands = {
        'textbf': ('<b class="negrito">', '</b>'),
        'emph': ('<i class="italico">', '</i>'),
        'textit': ('<i class="italico">', '</i>'),
        'texttt': ('<code class="codigo">', '</code>'),
        'footnote': (' (', ')'),
    }
    i = 0
    result = ""
    while i < len(text):
        if ((i == 0 or i == len(text)) and text[i] == " "):
            i += 1
        if text[i] == '\\':
            found = False
            for cmd, (open_tag, close_tag) in commands.items():
                prefix = f"\\{cmd}{{"
                if text.startswith(prefix, i):
                    found = True
                    start_content = i + len(prefix)
                    content_inside, end = extract_balanced(text, start_content)
                    inner = replace_formatting_commands(content_inside)
                    result += open_tag + inner + close_tag
                    i = end + 1
                    break
            if not found:
                result += text[i]
                i += 1
        else:
            result += text[i]
            i += 1
    return result

def replace_formatting(content: str, chapter_number: int) -> str:
    """
    Converte os comandos LaTeX de formatação para HTML, respeitando o balanceamento de chaves.
    """
    content = re.sub(
        r'\\chapter\{(.*?)\}',
        lambda m: f'<h1 class="capitulo">{chapter_number}. {m.group(1)}</h1>',
        content
    )
    content = replace_formatting_commands(content)
    return content

def replace_lists_and_paragraphs(content: str) -> str:
    """
    Converte listas do ambiente itemize e insere tags de parágrafo,
    mas ignora o conteúdo que já está dentro de blocos de código (<pre>).
    """
    # Converter listas
    content = re.sub(r'\\begin\{itemize\}', '<ul class="lista">', content)
    content = re.sub(r'\\end\{itemize\}', '</ul>', content)
    content = re.sub(r'\\item\s+(.*?)\n', r'  <li class="item">\1</li>\n', content)
    # return content
    # Dividir o conteúdo em blocos que estão dentro e fora de <pre>
    parts = re.split(r'(<pre.*?</pre>)', content, flags=re.DOTALL)
    for i, part in enumerate(parts):
        # Processar apenas as partes que não começam com <pre>
        if not part.strip().startswith("<pre"):
            # Insere tags de parágrafo para linhas que não sejam comandos LaTeX
            parts[i] = re.sub(
                r'(?m)^(?!\\|\s*$)(.+(?:\n(?!\s*$).+)*)$',
                r'<p class="paragrafo">\1</p>',
                part
            )
    return ''.join(parts)


def replace_quotes(content: str) -> str:
    """
    Converte aspas LaTeX para aspas normais.
    """
    content = re.sub(r"``", '"', content)
    content = re.sub(r"''", '"', content)
    return content

def build_html(content: str, chapter_title: str, chapter_number: int) -> str:
    """
    Constrói o documento HTML final.
    """
    start_html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Capítulo {chapter_number} - {chapter_title}</title>
  <link rel="stylesheet" href="../../style.css">
</head>
<body>
  <main>
    <nav class="back-button-container">
        <a href="../../index.html" class="back-button">← Voltar ao Índice</a>
    </nav>
"""
    end_html = """
  </main>
</body>
</html>
"""
    return start_html + content + end_html

def convert_latex_to_html(file_path: str, chapter_number: int) -> None:
    """
    Função principal que realiza a conversão de um arquivo LaTeX para HTML.
    """
    try:
        path = Path(file_path)
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Erro ao ler o arquivo: {e}")
        sys.exit(1)

    chapter_title_match = re.search(r'\\chapter\{(.*?)\}', content)
    chapter_title = chapter_title_match.group(1) if chapter_title_match else "Título não encontrado"

    # Registra todos os labels encontrados
    parse_labels(content)
    # Primeiro converte figuras antes de remover comandos que possam afetar o HTML
    content = re.sub(r'<(.*?)>', r'&lt;\1&gt;', content) # Escapa os sinais de menor e maior
    content = replace_figures(content)
    content = remove_latex_commands(content)
    content = replace_references(content)
    content = replace_code_blocks(content)
    content = replace_sections(content, chapter_number)
    content = replace_formatting(content, chapter_number)
    content = replace_lists_and_paragraphs(content)
    content = replace_quotes(content)
    content = replace_tables(content)

    html_content = build_html(content, chapter_title, chapter_number)

    output_path = path.parent / "index.html"
    try:
        output_path.write_text(html_content, encoding='utf-8')
        print(f"Conversão concluída! Arquivo salvo em: {output_path}")
    except Exception as e:
        print(f"Erro ao salvar o arquivo: {e}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Uso: python script.py <caminho_do_arquivo.tex> <número_do_capítulo>")
        sys.exit(1)
    tex_path = sys.argv[1]
    try:
        chapter_num = int(sys.argv[2])
    except ValueError:
        print("O número do capítulo deve ser um inteiro.")
        sys.exit(1)
    convert_latex_to_html(tex_path, chapter_num)
