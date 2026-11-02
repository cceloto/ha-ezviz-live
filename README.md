![EZVIZ Live for Home Assistant](https://raw.githubusercontent.com/cceloto/ha-ezviz-live/main/docs/images/banner.png)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![GitHub Release](https://img.shields.io/github/v/release/cceloto/ha-ezviz-live?include_prereleases)](https://github.com/cceloto/ha-ezviz-live/releases)
[![Validate](https://github.com/cceloto/ha-ezviz-live/actions/workflows/validate.yml/badge.svg)](https://github.com/cceloto/ha-ezviz-live/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/github/license/cceloto/ha-ezviz-live)](LICENSE)
[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-D97757)](#built-with-claude-code)

**[English](#english)** | **[Português (Brasil)](#português-brasil)**

---

## English

Live video and audio from EZVIZ cameras **through the EZVIZ cloud**, the same way the EZVIZ app does it — including battery devices that sleep and have no RTSP, such as the DP2C smart peephole.

> [!WARNING]
> Early beta (`0.0.x`). Unofficial project, not affiliated with EZVIZ or Hikvision. Developed primarily with an AI coding agent — see [Built with Claude Code](#built-with-claude-code).

### Tested hardware

> [!IMPORTANT]
> So far **one device** has been tested end to end. Every other model is unconfirmed — see [Compatibility](#compatibility).

| Device | Model | Firmware | Power | Home Assistant | Result |
|---|---|---|---|---|---|
| EZVIZ DP2C smart peephole | `CS-DP2C-R100-6E2WPFB-GD` | V5.3.3 build 250911 | Battery | 2026.10.4, HA OS on Raspberry Pi 4 | ✅ Live video (HEVC 1080p/720p, 15 fps) and audio (AAC 16 kHz) over HLS; wakes in ~3 s |

### Features

- 📹 Live view with audio in the native camera card, the more-info dialog and the Home Assistant mobile app.
- 🔋 Battery friendly: the device is woken **only while someone is watching**, and the session closes about 35 s after the last viewer leaves.
- 🖼️ Thumbnails never wake the device: they show the last frame of the previous session or, before that, the last motion picture from the EZVIZ integration.
- 🔑 No extra login: reuses the session of the core **EZVIZ** integration. No password is asked for or stored.
- 🧩 The camera joins the existing EZVIZ device (same area, same device page).
- 🌍 English and Brazilian Portuguese, chosen by Home Assistant's language settings.
- 🛠️ Diagnostics download with masked serials, for bug reports.

### How it works

```
EZVIZ cloud ──(VTM → VTDU, encrypted)──▶ ezviz_live ──MPEG-PS──▶ HA stream ──HLS──▶ dashboard / app
                                              ▲
                     session borrowed from the core EZVIZ integration
```

The integration speaks the EZVIZ stream-server protocol (VTM/VTDU), decrypts the media and hands an MPEG-PS feed to Home Assistant's built-in `stream` component through a local relay on `127.0.0.1`. Home Assistant then serves it as HLS. Video is copied, never transcoded, so it runs fine on a Raspberry Pi 4. Protocol details are in [docs/protocol.md](docs/protocol.md).

### Requirements

- Home Assistant **2026.10** or newer.
- The core **[EZVIZ](https://www.home-assistant.io/integrations/ezviz/)** integration set up with your **cloud account** (two-factor authentication must be off, as the core integration requires).
- The device must open live view in the EZVIZ app.

### Installation

#### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cceloto&repository=ha-ezviz-live&category=integration)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/cceloto/ha-ezviz-live`, type **Integration**.
2. Search for **EZVIZ Live** and download it.
3. Restart Home Assistant.

#### Manual

1. Copy `custom_components/ezviz_live` into `<config>/custom_components/ezviz_live`.
2. Restart Home Assistant.

### Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ezviz_live)

**Settings → Devices & services → Add integration → EZVIZ Live**, then pick the EZVIZ account. One camera entity is created per live-capable channel, named after the device.

#### Options

| Option | Default | Description |
|---|---|---|
| Quality | Main stream | Main (highest resolution) or sub stream (lighter). |
| Allow WebRTC (go2rtc) | Off | Many EZVIZ cameras send **H.265**. Off: HLS only, which works everywhere. On: go2rtc tries WebRTC, lower latency, but H.265 only shows in browsers that support it. |

### Languages

The integration ships **English** and **Português (Brasil)**. Home Assistant decides which one you see:

| What | Language used | Where to change it |
|---|---|---|
| Setup wizard, options and repair messages | Your **user profile** language | Profile → Language |
| Entity names and entity IDs | The **system** language | Settings → System → General |

Any other language falls back to English. Entity IDs follow Home Assistant's rules, so the same camera becomes `camera.front_door_live` on an English system and `camera.porta_ao_vivo` on a Portuguese one. Want another language? Open a [documentation & translations](https://github.com/cceloto/ha-ezviz-live/issues/new?template=documentation.yml) issue.

### Usage

Use any camera card. To save battery, prefer `camera_view: auto`: the card shows the thumbnail and live view starts only when you open it.

```yaml
type: picture-entity
entity: camera.front_door_live
camera_view: auto
```

> [!CAUTION]
> `camera_view: live` starts the stream every time the dashboard is open, which keeps a battery device awake.

Expect the first image about **10–12 s** after opening: about 3 s for the device to wake up, plus the time HLS needs to build its first segment.

### Compatibility

**Legend:** ✅ verified on real hardware · 🟡 expected to work (same cloud path), not confirmed yet · 🧪 implemented, never tested on real hardware · ❌ not supported

#### Device types

| Device type | Examples | Status | Notes |
|---|---|---|---|
| Battery doorbells and peepholes that sleep | DP2C | ✅ | See [Tested hardware](#tested-hardware). |
| Other battery cameras | BC1C, CB-series | 🟡 | Same path as the DP2C. |
| Wired single-channel cameras, with or without RTSP | C6N, C3TN, H6c, DB2 | 🟡 | For RTSP models this adds remote viewing; local RTSP through the core integration stays faster. |
| Image encryption ("verification code") turned on | Many models by default | 🧪 | Add the camera to the core EZVIZ integration with its verification code; otherwise a repair issue explains what to do. |
| Multi-channel devices | NVR/DVR, base stations, dual-lens doorbells | 🧪 | One entity per channel. |
| Stream servers that require TLS | Some models and regions | ❌ | Not implemented yet. |
| End-to-end encryption (E2EE) enabled | Newer models | ❌ | Impossible without the device key. |

#### Features

| Feature | Status |
|---|---|
| Live video (H.264 and H.265) | ✅ HLS |
| Live audio | ✅ AAC |
| Thumbnails without waking the device | ✅ |
| WebRTC through go2rtc | 🧪 opt-in, H.265 depends on the browser |
| Two-way talk | ❌ planned |
| Recordings / playback | ❌ |
| PTZ, sirens, lights | ❌ — use the core EZVIZ integration |

#### Is my device a candidate?

1. Live view works in the EZVIZ app **away from home** (on mobile data). That is the cloud path this integration uses.
2. The device shows up in the core EZVIZ integration.
3. After adding EZVIZ Live, a camera entity is created for it. No entity means the cloud does not offer live view for it.

Whatever the result, please send a **[device report](https://github.com/cceloto/ha-ezviz-live/issues/new?template=device_report.yml)**. It is how this table grows.

### Troubleshooting

- **Entity attributes**: `live_state` (`idle`, `opening`, `streaming`), `viewers`, `last_open_seconds`, `last_error`.
- **Repairs**: a repair issue tells you when a device has image encryption on and no verification code.
- **Debug log**:
  ```yaml
  logger:
    logs:
      custom_components.ezviz_live: debug
  ```
- **Diagnostics**: Settings → Devices & services → EZVIZ Live → ⋮ → Download diagnostics.

| `last_error` contains | Meaning |
|---|---|
| `VTDU refused the stream: 6001` / `5569` | Request rejected by the stream server (authentication). Please report it. |
| `ezviz_not_loaded` | The core EZVIZ integration is not loaded (restarting, offline, or needs re-authentication). |
| `verification code` | Image encryption is on; see Compatibility. |

### Contributing

Pick the issue type that fits (English or Portuguese are both fine):

| Issue | For |
|---|---|
| [🐞 Bug report](https://github.com/cceloto/ha-ezviz-live/issues/new?template=bug_report.yml) | Something does not work as described |
| [📷 Device report](https://github.com/cceloto/ha-ezviz-live/issues/new?template=device_report.yml) | Whether your camera works or not |
| [✨ Feature request](https://github.com/cceloto/ha-ezviz-live/issues/new?template=feature_request.yml) | New features or behavior changes |
| [📝 Documentation, texts and translations](https://github.com/cceloto/ha-ezviz-live/issues/new?template=documentation.yml) | README, protocol notes, UI texts, new languages |

Development:

- Tests: `pip install -r requirements_test.txt && pytest`.
- Branches: pull requests target **`develop`**; `main` only receives releases from `develop`.
- Versioning: [Semantic Versioning](https://semver.org/). `0.x.y` releases may change behavior between minor versions. See [CHANGELOG.md](CHANGELOG.md).

### Built with Claude Code

This project was developed primarily with **[Claude Code](https://claude.com/claude-code)**, Anthropic's AI coding agent. Claude Code carried out the protocol analysis, wrote the integration code, the tests and this documentation, and ran the validation against the real device. The maintainer set the goals, made the decisions, reviewed the changes and tested them on a real device and a real Home Assistant installation. Commits made this way carry a `Co-Authored-By: Claude` trailer.

That means the code has had one human reviewer so far. Reviews, bug reports and device reports from the community are especially welcome.

### Disclaimer

This is an unofficial, independent interoperability project for personal use. It is not affiliated with, endorsed by or supported by EZVIZ or Hikvision. "EZVIZ" is a trademark of its owner. The cloud protocol may change at any time and break this integration. Use at your own risk and within the EZVIZ terms of service.

### License

[MIT](LICENSE)

---

## Português (Brasil)

Vídeo e áudio ao vivo de câmeras EZVIZ **pela nuvem EZVIZ**, do mesmo jeito que o app EZVIZ faz, inclusive aparelhos a bateria que dormem e não têm RTSP, como o olho mágico DP2C.

> [!WARNING]
> Beta inicial (`0.0.x`). Projeto não oficial, sem vínculo com a EZVIZ ou a Hikvision. Desenvolvido principalmente com um agente de IA para programação; veja [Desenvolvido com Claude Code](#desenvolvido-com-claude-code).

### Hardware testado

> [!IMPORTANT]
> Até agora **um aparelho** foi testado de ponta a ponta. Todos os outros modelos ainda não foram confirmados; veja [Compatibilidade](#compatibilidade).

| Aparelho | Modelo | Firmware | Alimentação | Home Assistant | Resultado |
|---|---|---|---|---|---|
| Olho mágico EZVIZ DP2C | `CS-DP2C-R100-6E2WPFB-GD` | V5.3.3 build 250911 | Bateria | 2026.10.4, HA OS no Raspberry Pi 4 | ✅ Vídeo ao vivo (HEVC 1080p/720p, 15 fps) e áudio (AAC 16 kHz) por HLS; acorda em ~3 s |

### Recursos

- 📹 Ao vivo com áudio no cartão de câmera nativo, no diálogo de detalhes e no app do Home Assistant.
- 🔋 Poupa bateria: o aparelho só acorda **enquanto alguém está assistindo**, e a sessão fecha uns 35 s depois que o último sai.
- 🖼️ A miniatura nunca acorda o aparelho: mostra o último quadro da sessão anterior ou, antes disso, a foto do último movimento da integração EZVIZ.
- 🔑 Sem login extra: reaproveita a sessão da integração **EZVIZ** nativa. Nenhuma senha é pedida ou guardada.
- 🧩 A câmera entra no aparelho EZVIZ que já existe (mesma área, mesma página).
- 🌍 Inglês e português do Brasil, escolhidos pelas configurações de idioma do Home Assistant.
- 🛠️ Diagnóstico para download com serial mascarado, para relatar problemas.

### Como funciona

```
nuvem EZVIZ ──(VTM → VTDU, cifrado)──▶ ezviz_live ──MPEG-PS──▶ stream do HA ──HLS──▶ painel / app
                                              ▲
                    sessão emprestada da integração EZVIZ nativa
```

A integração fala o protocolo dos servidores de vídeo da EZVIZ (VTM/VTDU), decifra a mídia e entrega um fluxo MPEG-PS ao componente `stream` do Home Assistant por um relay local em `127.0.0.1`. O Home Assistant serve isso como HLS. O vídeo é copiado, nunca recodificado, e roda bem num Raspberry Pi 4. Detalhes do protocolo em [docs/protocol.md](docs/protocol.md).

### Requisitos

- Home Assistant **2026.10** ou mais novo.
- A integração **[EZVIZ](https://www.home-assistant.io/integrations/ezviz/)** nativa configurada com a sua **conta na nuvem** (autenticação em duas etapas desligada, como a integração nativa exige).
- O aparelho precisa abrir o ao vivo no app EZVIZ.

### Instalação

#### HACS (recomendado)

[![Abra o seu Home Assistant e abra um repositório no HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cceloto&repository=ha-ezviz-live&category=integration)

1. HACS → ⋮ → **Repositórios personalizados** → adicione `https://github.com/cceloto/ha-ezviz-live`, tipo **Integração**.
2. Procure **EZVIZ Live** e baixe.
3. Reinicie o Home Assistant.

#### Manual

1. Copie `custom_components/ezviz_live` para `<config>/custom_components/ezviz_live`.
2. Reinicie o Home Assistant.

### Configuração

[![Abra o seu Home Assistant e comece a configurar uma integração.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ezviz_live)

**Configurações → Dispositivos e serviços → Adicionar integração → EZVIZ Live**, e escolha a conta EZVIZ. É criada uma câmera por canal com ao vivo, com o nome do aparelho.

#### Opções

| Opção | Padrão | Descrição |
|---|---|---|
| Qualidade | Principal | Principal (maior resolução) ou secundário (mais leve). |
| Permitir WebRTC (go2rtc) | Desligado | Muitas câmeras EZVIZ mandam **H.265**. Desligado: só HLS, que funciona em todo lugar. Ligado: o go2rtc tenta WebRTC, com menos atraso, mas H.265 só aparece em navegadores compatíveis. |

### Idiomas

A integração vem em **inglês** e **português do Brasil**. É o Home Assistant que decide qual você vê:

| O quê | Idioma usado | Onde mudar |
|---|---|---|
| Assistente de configuração, opções e avisos de reparo | O idioma do seu **perfil de usuário** | Perfil → Idioma |
| Nomes e IDs das entidades | O idioma do **sistema** | Configurações → Sistema → Geral |

Qualquer outro idioma cai no inglês. Os IDs seguem as regras do Home Assistant: a mesma câmera vira `camera.front_door_live` num sistema em inglês e `camera.porta_ao_vivo` num sistema em português. Quer outro idioma? Abra uma issue de [documentação e traduções](https://github.com/cceloto/ha-ezviz-live/issues/new?template=documentation.yml).

### Uso

Qualquer cartão de câmera serve. Para poupar bateria, prefira `camera_view: auto`: o cartão mostra a miniatura e o ao vivo só começa quando você abre.

```yaml
type: picture-entity
entity: camera.porta_ao_vivo
camera_view: auto
```

> [!CAUTION]
> `camera_view: live` inicia o stream sempre que o painel está aberto, o que mantém um aparelho a bateria acordado.

A primeira imagem aparece uns **10–12 s** depois de abrir: cerca de 3 s para o aparelho acordar, mais o tempo que o HLS leva para montar o primeiro segmento.

### Compatibilidade

**Legenda:** ✅ confirmado em aparelho real · 🟡 deve funcionar (mesmo caminho na nuvem), ainda não confirmado · 🧪 implementado, nunca testado em aparelho real · ❌ não suportado

#### Tipos de aparelho

| Tipo | Exemplos | Situação | Observações |
|---|---|---|---|
| Campainhas e olhos mágicos a bateria, que dormem | DP2C | ✅ | Veja [Hardware testado](#hardware-testado). |
| Outras câmeras a bateria | BC1C, linha CB | 🟡 | Mesmo caminho do DP2C. |
| Câmeras com fio de um canal, com ou sem RTSP | C6N, C3TN, H6c, DB2 | 🟡 | Nos modelos com RTSP isto acrescenta o acesso remoto; o RTSP local pela integração nativa continua mais rápido. |
| Criptografia de imagem ("código de verificação") ligada | Padrão de fábrica em muitos modelos | 🧪 | Adicione a câmera na integração EZVIZ nativa com o código de verificação; senão um aviso de reparo explica o que fazer. |
| Aparelhos com vários canais | NVR/DVR, bases, campainhas com duas lentes | 🧪 | Uma entidade por canal. |
| Servidores de vídeo que exigem TLS | Alguns modelos e regiões | ❌ | Ainda não implementado. |
| Criptografia ponta a ponta (E2EE) ligada | Modelos novos | ❌ | Impossível sem a chave do aparelho. |

#### Recursos

| Recurso | Situação |
|---|---|
| Vídeo ao vivo (H.264 e H.265) | ✅ HLS |
| Áudio ao vivo | ✅ AAC |
| Miniatura sem acordar o aparelho | ✅ |
| WebRTC pelo go2rtc | 🧪 opcional; H.265 depende do navegador |
| Conversa bidirecional | ❌ planejado |
| Gravações / reprodução | ❌ |
| PTZ, sirene, luzes | ❌ use a integração EZVIZ nativa |

#### O meu aparelho é candidato?

1. O ao vivo funciona no app EZVIZ **fora de casa** (nos dados móveis). É esse caminho pela nuvem que a integração usa.
2. O aparelho aparece na integração EZVIZ nativa.
3. Depois de adicionar a EZVIZ Live, uma câmera é criada para ele. Sem entidade, a nuvem não oferece ao vivo para esse aparelho.

Seja qual for o resultado, mande um **[relato de aparelho](https://github.com/cceloto/ha-ezviz-live/issues/new?template=device_report.yml)**. É assim que esta tabela cresce.

### Solução de problemas

- **Atributos da entidade**: `live_state` (`idle`, `opening`, `streaming`), `viewers`, `last_open_seconds`, `last_error`.
- **Reparos**: um aviso aparece quando um aparelho está com criptografia de imagem ligada e sem código de verificação.
- **Log de depuração**:
  ```yaml
  logger:
    logs:
      custom_components.ezviz_live: debug
  ```
- **Diagnóstico**: Configurações → Dispositivos e serviços → EZVIZ Live → ⋮ → Baixar diagnóstico.

| `last_error` contém | Significado |
|---|---|
| `VTDU refused the stream: 6001` / `5569` | Pedido recusado pelo servidor de vídeo (autenticação). Por favor, relate. |
| `ezviz_not_loaded` | A integração EZVIZ nativa não está carregada (reiniciando, sem internet ou pedindo nova autenticação). |
| `verification code` | Criptografia de imagem ligada; veja Compatibilidade. |

### Como contribuir

Escolha o tipo de issue que se encaixa (pode escrever em inglês ou português):

| Issue | Para |
|---|---|
| [🐞 Bug report](https://github.com/cceloto/ha-ezviz-live/issues/new?template=bug_report.yml) | Algo não funciona como descrito |
| [📷 Device report](https://github.com/cceloto/ha-ezviz-live/issues/new?template=device_report.yml) | Se a sua câmera funciona ou não |
| [✨ Feature request](https://github.com/cceloto/ha-ezviz-live/issues/new?template=feature_request.yml) | Recursos novos ou mudança de comportamento |
| [📝 Documentation, texts and translations](https://github.com/cceloto/ha-ezviz-live/issues/new?template=documentation.yml) | README, notas do protocolo, textos da interface, novos idiomas |

Desenvolvimento:

- Testes: `pip install -r requirements_test.txt && pytest`.
- Branches: pull requests vão para a **`develop`**; a `main` só recebe versões vindas da `develop`.
- Versões: [Semantic Versioning](https://semver.org/lang/pt-BR/). Versões `0.x.y` podem mudar de comportamento entre versões menores. Veja o [CHANGELOG.md](CHANGELOG.md).

### Desenvolvido com Claude Code

Este projeto foi desenvolvido principalmente com o **[Claude Code](https://claude.com/claude-code)**, o agente de IA para programação da Anthropic. O Claude Code fez a análise do protocolo, escreveu o código da integração, os testes e esta documentação, e rodou a validação contra o aparelho real. O mantenedor definiu os objetivos, tomou as decisões, revisou as mudanças e testou no próprio hardware e no próprio Home Assistant. Os commits feitos assim levam a linha `Co-Authored-By: Claude`.

Isso quer dizer que, até agora, o código teve um único revisor humano. Revisões, relatos de bug e relatos de aparelho da comunidade são especialmente bem-vindos.

### Aviso

Projeto independente e não oficial de interoperabilidade, para uso pessoal. Não tem vínculo, aprovação nem suporte da EZVIZ ou da Hikvision. "EZVIZ" é marca do seu titular. O protocolo da nuvem pode mudar a qualquer momento e quebrar esta integração. Use por sua conta e risco e dentro dos termos de uso da EZVIZ.

### Licença

[MIT](LICENSE)
