# wordCensor

Ferramenta desktop para Windows que borra informações sensíveis (e-mails, nomes, dados pessoais) em gravações de tela.

## Funcionalidades

- Desenhe regiões de desfoque em qualquer frame do vídeo
- Rastreamento automático usando correlação de fase + fluxo óptico Lucas-Kanade
- Suporte a rastreamento retroativo (backward tracking)
- Defina frame de início e fim por região
- Correção manual de posição em qualquer frame
- Desfoque gaussiano com borda suavizada
- Exportação em MP4 com áudio original preservado (via FFmpeg)

## Requisitos

- Python 3.10+
- FFmpeg — coloque o `ffmpeg.exe` numa pasta `ffmpeg/` ao lado da raiz do projeto, ou tenha-o no PATH do sistema

## Instalação

```bash
pip install -r requirements.txt
```

## Executar

```bash
python app/main.py
```

Ou clique duas vezes em `dev_run.bat` no Windows.

## Como usar

1. Abra um arquivo de vídeo
2. Desenhe um retângulo sobre a área que deseja borrar
3. Avance pelos frames — o rastreamento atualiza automaticamente
4. Use **Correct Position** para corrigir o desvio em qualquer frame
5. Use **Set Start Here / Set End Here** para controlar o intervalo ativo de cada região
6. Clique em **Export MP4** quando terminar

## Estrutura do projeto

```
app/
  main.py               # Ponto de entrada
  core/
    region.py           # Modelo de dados BlurRegion
    tracker.py          # Rastreador por correlação de fase + LK
    blurrer.py          # Desfoque gaussiano com borda suavizada
    exporter.py         # Exportação de vídeo via pipe FFmpeg
  ui/
    main_window.py      # Janela principal da aplicação
    video_canvas.py     # Widget de exibição de vídeo e desenho de regiões
    timeline_markers.py # Barra de timeline mostrando os intervalos de cada região
```
