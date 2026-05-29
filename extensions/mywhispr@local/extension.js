import GObject from 'gi://GObject';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Soup from 'gi://Soup';
import GLib from 'gi://GLib';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const STATUS_URL = 'http://127.0.0.1:16666/api/status';
const POLL_MS = 600;

function modeMarker(status) {
    if ((status.current_mode_type || '') === 'script')
        return '🤖';
    const lang = status.current_language || '';
    if (lang === 'uk')
        return '🇺🇦';
    if (lang === 'en')
        return '🇺🇸';
    if (lang)
        return `[${lang}]`;
    return '';
}

const Indicator = GObject.registerClass(
class Indicator extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'MyWhispr', false);
        this._session = new Soup.Session();
        this._session.timeout = 2;
        this._icon = new St.Icon({
            icon_name: 'audio-input-microphone-symbolic',
            style_class: 'system-status-icon',
        });
        this._label = new St.Label({
            y_align: Clutter.ActorAlign.CENTER,
            text: '',
            style_class: 'mywhispr-label',
        });
        const box = new St.BoxLayout({vertical: false});
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        // Popup menu items
        this._textItem = new PopupMenu.PopupMenuItem('—');
        this._textItem.label.style_class = 'mywhispr-popup-text';
        this._textItem.connect('activate', () => this._copyLast());
        this.menu.addMenuItem(this._textItem);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._stopItem = new PopupMenu.PopupMenuItem('Stop recording');
        this._stopItem.connect('activate', () => this._stopRecording());
        this.menu.addMenuItem(this._stopItem);
        this._openItem = new PopupMenu.PopupMenuItem('Open web UI');
        this._openItem.connect('activate', () => this._openUI());
        this.menu.addMenuItem(this._openItem);

        this._lastText = '';
        this._timerId = 0;
        this._tick();
    }

    _tick() {
        const msg = Soup.Message.new('GET', STATUS_URL);
        this._session.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, (s, res) => {
            try {
                const bytes = s.send_and_read_finish(res);
                const data = JSON.parse(new TextDecoder().decode(bytes.get_data()));
                this._apply(data);
            } catch (_e) {
                this._dim();
            }
            this._scheduleNext();
        });
    }

    _scheduleNext() {
        if (this._timerId) GLib.source_remove(this._timerId);
        this._timerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, POLL_MS, () => {
            this._timerId = 0;
            this._tick();
            return GLib.SOURCE_REMOVE;
        });
    }

    _apply(status) {
        this._icon.opacity = 255;
        const topbar = status.topbar || {};
        if (topbar.enabled === false) {
            this._label.text = '';
            this._icon.opacity = 100;
            return;
        }
        const state = status.state || 'IDLE';
        const isRec = state === 'RECORDING' || state === 'STARTING';
        const isBusy = state === 'TRANSCRIBING' || state === 'TRANSCRIBING_NO_PASTE'
                       || state === 'STOPPING' || state === 'STOPPING_NO_PASTE' || state === 'PASTING';
        this._label.style_class = 'mywhispr-label' + (isRec ? ' mywhispr-recording' :
                                                     isBusy ? ' mywhispr-busy' : '');
        let text = '';
        if (isRec) {
            const marker = modeMarker(status);
            text = (marker ? `${marker} ` : '') + (status.live_preview || '…');
        } else if (status.retranslate && status.retranslate.active) {
            text = `retr ${status.retranslate.done}/${status.retranslate.total}`;
        } else if (topbar.show_when_idle !== false) {
            text = status.last_transcript || '';
        }
        const maxWords = Number(topbar.max_words || 10);
        const words = (text || '').trim().split(/\s+/).filter(Boolean);
        const shown = words.length > maxWords ? '…' + words.slice(-maxWords).join(' ') : words.join(' ');
        this._label.text = shown;
        this._lastText = status.last_transcript || '';
        this._textItem.label.text = this._lastText || '(no transcript yet)';
        if (typeof this._stopItem.setSensitive === 'function')
            this._stopItem.setSensitive(isRec);
        else if (this._stopItem.actor)
            this._stopItem.actor.reactive = isRec;
        else
            this._stopItem.reactive = isRec;
    }

    _dim() {
        this._icon.opacity = 100;
        this._label.text = '';
        this._label.style_class = 'mywhispr-label mywhispr-error';
    }

    _copyLast() {
        if (!this._lastText) return;
        const clip = St.Clipboard.get_default();
        clip.set_text(St.ClipboardType.CLIPBOARD, this._lastText);
    }

    _stopRecording() {
        const msg = Soup.Message.new('POST', 'http://127.0.0.1:16666/api/recording/stop');
        msg.set_request_body_from_bytes('application/json', new GLib.Bytes(new TextEncoder().encode('{}')));
        this._session.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, () => {});
    }

    _openUI() {
        GLib.spawn_command_line_async('xdg-open http://127.0.0.1:16666/');
    }

    destroy() {
        if (this._timerId) GLib.source_remove(this._timerId);
        this._timerId = 0;
        super.destroy();
    }
});

export default class MyWhisprExtension extends Extension {
    enable() {
        this._indicator = new Indicator();
        Main.panel.addToStatusArea('mywhispr', this._indicator);
    }
    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
