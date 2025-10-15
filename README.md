# MTechClicker

Autoclicker + Macro rápido, leve e **compatível com jogos**, feito para automação precisa e responsiva em qualquer cenário.  
Atalhos globais, gravação de macro, tema escuro e execução em segundo plano com suporte a bandeja do sistema.

> ⚠️ **Aviso:** use de forma ética e responsável, respeitando os Termos de Uso dos softwares e jogos.

---

## ✨ Recursos

- 🖱️ **Autoclick** e 🎬 **Macro (sequência)** em abas separadas
- 🎮 **Compatível com jogos** (usa `pydirectinput` e `pyautogui`)
- ⌨️ **Atalhos globais configuráveis** (inclusive botões do mouse)
- 🕹️ **Execução em segundo plano / bandeja (tray)**
- 🕒 **Delay base e variação aleatória** para cliques naturais
- 💾 **Salvar e carregar configurações automaticamente (`settings.json`)**
- 🔐 **FailSafe**: mover o mouse para o canto superior esquerdo interrompe tudo
- 🌙 **Tema escuro com `ttkbootstrap`**
- 🔁 **Macros com ou sem posição do cursor**
- 🚨 **Hotkey de emergência** (pausa instantânea)

---

## ⚙️ Instalação (Modo desenvolvedor)

1. Clone o repositório:

   ```bash
   git clone git@github.com:mercuridev/autoclick-py.git
   cd autoclick-py
   ```

2. Crie o ambiente virtual e ative:

   ```bash
   python -m venv venv

   # PowerShell
   .\venv\Scripts\Activate.ps1

   # Git Bash
   source venv/Scripts/activate
   ```

3. Instale as dependências:

   ```bash
   pip install -U pip setuptools wheel
   pip install pyautogui pydirectinput pynput pillow pystray ttkbootstrap
   ```

4. Execute:
   ```bash
   python main.py
   ```

---

## 🧱 Gerar Executável (.exe)

Para gerar o executável autônomo do **MTechClicker**, utilize o comando abaixo:

```bash
python -m PyInstaller --onefile --noconsole --name MTechClicker --uac-admin --hidden-import=pystray._win32 main.py
```

### 📘 Explicação do comando

| Parâmetro                        | Função                                                    |
| -------------------------------- | --------------------------------------------------------- |
| `--onefile`                      | Gera um único arquivo `.exe` compacto                     |
| `--noconsole`                    | Remove o terminal de fundo                                |
| `--name MTechClicker`            | Define o nome do executável                               |
| `--uac-admin`                    | Garante execução como administrador (necessário em jogos) |
| `--hidden-import=pystray._win32` | Inclui dependências que o PyInstaller ignora por padrão   |
| `main.py`                        | Script principal do aplicativo                            |

O arquivo final será criado em:

```
dist/MTechClicker.exe
```

> 🧠 **Dica:** se quiser ver logs de erro durante o build, use `--console` no lugar de `--noconsole`.

---

## 🧩 Como usar

### 🔹 Geral

- Configure os atalhos **Iniciar/Parar** e **Emergência** (podem ser teclas ou botões do mouse).
- Defina um **delay inicial (countdown)**, se quiser tempo antes da execução.

### 🔹 Aba Autoclick

- Escolha o **botão** (left/right/middle) e **tipo de clique** (single/double).
- Defina **delay base** e **variação (%)** para tornar os cliques naturais.
- Opção de **posição fixa** ou **seguir o cursor atual**.
- Modo de execução:
  - `until_stop` → executa até ser parado
  - `fixed_amount` → executa por número definido de cliques

### 🔹 Aba Macro

- Grave uma sequência de ações (cliques e teclas).
- O sistema ignora automaticamente cliques dentro da janela do app.
- Escolha se quer **usar posições gravadas** ou **clicar no cursor atual**.
- Escolha `0` loops para execução infinita.

### 🔹 Bandeja (System Tray)

- Ao minimizar, o programa vai para a **bandeja**.
- Clique com o direito para **abrir, iniciar/parar ou sair**.

---

## 🛠️ Solução de Problemas

**Erro “No module named X” ao abrir o .exe**  
→ Adicione `--hidden-import=X` no comando do PyInstaller.

**O autoclick não funciona no jogo**  
→ Execute o `MTechClicker.exe` como **Administrador**.

**Os botões laterais do mouse não funcionam como hotkey**  
→ Configure o botão no software do mouse como tecla (`PgUp`, `PgDn`, etc.).

**Texto cortado ou interface bugada**  
→ Ajuste o _scaling_ do Windows (recomenda-se 100% a 125%).

---

## 📦 Estrutura do Projeto

```
mtechclicker/
├── main.py
├── settings.json
├── requirements.txt
├── README.md
└── dist/
    └── MTechClicker.exe
```

---

## 📜 Licença

Distribuído sob a licença **MIT**.  
© 2025 Mercuri Tech — Todos os direitos reservados.
