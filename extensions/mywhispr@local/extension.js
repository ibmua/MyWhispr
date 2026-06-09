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
const COPY_BUTTON_LABELS = ['Copy latest dictation', 'Copy previous dictation'];
const COPY_SNIPPET_CHARS = 32;

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

function menuSnippet(text) {
    const flat = (text || '').replace(/\s+/g, ' ').trim();
    if (flat.length <= 72)
        return flat;
    return `${flat.slice(0, 71)}…`;
}

function buttonSnippet(text) {
    const flat = (text || '').replace(/\s+/g, ' ').trim();
    if (flat.length <= COPY_SNIPPET_CHARS)
        return flat;
    return `${flat.slice(0, COPY_SNIPPET_CHARS - 1)}…`;
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
        this._copyButtons = [];
        for (let i = 0; i < 2; i++) {
            const button = this._makeCopyButton(i);
            this._copyButtons.push(button);
            box.add_child(button);
        }
        box.add_child(this._label);
        this.add_child(box);

        this._copyRows = [];
        for (let i = 0; i < 2; i++) {
            const row = this._makeCopyMenuRow(i);
            this._copyRows.push(row);
            this.menu.addMenuItem(row.item);
        }
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._stopItem = new PopupMenu.PopupMenuItem('Stop recording');
        this._stopItem.connect('activate', () => this._stopRecording());
        this.menu.addMenuItem(this._stopItem);
        this._openItem = new PopupMenu.PopupMenuItem('Open web UI');
        this._openItem.connect('activate', () => this._openUI());
        this.menu.addMenuItem(this._openItem);

        this._recentTranscripts = [];
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
        const state = status.state || 'IDLE';
        const isRec = state === 'RECORDING' || state === 'STARTING';
        const isBusy = state === 'TRANSCRIBING' || state === 'TRANSCRIBING_NO_PASTE'
                       || state === 'STOPPING' || state === 'STOPPING_NO_PASTE' || state === 'PASTING';
        this._updateCopyItems(status);
        this._setItemSensitive(this._stopItem, isRec);
        if (topbar.enabled === false) {
            this._label.text = '';
            this._icon.opacity = 100;
            return;
        }
        this._label.style_class = 'mywhispr-label' + (isRec ? ' mywhispr-recording' :
                                                     isBusy ? ' mywhispr-busy' : '');
        let text = '';
        if (isRec) {
            const marker = modeMarker(status);
            text = (marker ? `${marker} ` : '') + (status.live_preview || '…');
        } else if (status.retranslate && status.retranslate.active) {
            text = `retr ${status.retranslate.done}/${status.retranslate.total}`;
        } else if (topbar.show_when_idle !== false) {
            text = '';
        }
        const maxWords = Number(topbar.max_words || 10);
        const words = (text || '').trim().split(/\s+/).filter(Boolean);
        const shown = words.length > maxWords ? '…' + words.slice(-maxWords).join(' ') : words.join(' ');
        this._label.text = shown;
    }

    _dim() {
        this._icon.opacity = 100;
        this._label.text = '';
        this._label.style_class = 'mywhispr-label mywhispr-error';
    }

    _updateCopyItems(status) {
        const recent = Array.isArray(status.recent_transcripts) ? status.recent_transcripts : [];
        const texts = recent
            .map((item) => `${item && item.text ? item.text : ''}`)
            .filter((text) => text.trim());
        if (!texts.length && status.last_transcript)
            texts.push(status.last_transcript);
        this._recentTranscripts = texts.slice(0, 2);

        for (let i = 0; i < this._copyRows.length; i++) {
            const text = this._recentTranscripts[i] || '';
            const row = this._copyRows[i];
            row.label.text = text
                ? menuSnippet(text)
                : (i === 0 ? 'No transcript yet' : 'No previous transcript');
            row.button.reactive = Boolean(text);
            row.button.can_focus = Boolean(text);
            row.button.opacity = text ? 255 : 80;
            this._setCopyButtonSensitive(this._copyButtons[i], Boolean(text), text);
        }
    }

    _makeCopyMenuRow(index) {
        const item = new PopupMenu.PopupBaseMenuItem({
            reactive: false,
            can_focus: false,
            style_class: 'mywhispr-copy-row-item',
        });
        const box = new St.BoxLayout({
            vertical: false,
            style_class: 'mywhispr-copy-row',
        });
        const buttonContent = new St.BoxLayout({
            vertical: false,
            style_class: 'mywhispr-copy-row-button-content',
        });
        buttonContent.add_child(new St.Icon({
            icon_name: 'edit-copy-symbolic',
            style_class: 'system-status-icon mywhispr-copy-row-icon',
        }));
        buttonContent.add_child(new St.Label({
            y_align: Clutter.ActorAlign.CENTER,
            text: 'Copy',
            style_class: 'mywhispr-copy-row-button-label',
        }));
        const button = new St.Button({
            child: buttonContent,
            reactive: false,
            can_focus: false,
            track_hover: true,
            accessible_name: COPY_BUTTON_LABELS[index],
            style_class: 'mywhispr-copy-row-button',
        });
        button.connect('clicked', () => this._copyRecent(index));
        const label = new St.Label({
            y_align: Clutter.ActorAlign.CENTER,
            text: index === 0 ? 'No transcript yet' : 'No previous transcript',
            style_class: 'mywhispr-copy-row-text',
        });
        box.add_child(button);
        box.add_child(label);
        item.add_child(box);
        return {item, button, label};
    }

    _makeCopyButton(index) {
        const content = new St.BoxLayout({
            vertical: false,
            style_class: 'mywhispr-copy-button-content',
        });
        content.add_child(new St.Icon({
            icon_name: 'edit-copy-symbolic',
            style_class: 'system-status-icon mywhispr-copy-icon',
        }));
        const label = new St.Label({
            y_align: Clutter.ActorAlign.CENTER,
            text: 'Copy',
            style_class: 'mywhispr-copy-text',
        });
        content.add_child(label);

        const button = new St.Button({
            child: content,
            reactive: false,
            can_focus: false,
            track_hover: true,
            accessible_name: COPY_BUTTON_LABELS[index],
            style_class: 'mywhispr-copy-button',
        });
        button.connect('clicked', () => this._copyRecent(index));
        button._mywhisprLabel = label;
        return button;
    }

    _setItemSensitive(item, sensitive) {
        if (typeof item.setSensitive === 'function')
            item.setSensitive(sensitive);
        else if (item.actor)
            item.actor.reactive = sensitive;
        else
            item.reactive = sensitive;
    }

    _setCopyButtonSensitive(button, sensitive, text) {
        if (!button) return;
        button.reactive = sensitive;
        button.can_focus = sensitive;
        button.opacity = sensitive ? 255 : 75;
        if (button._mywhisprLabel) {
            button._mywhisprLabel.text = sensitive
                ? `Copy: ${buttonSnippet(text)}`
                : 'Copy';
        }
    }

    _copyRecent(index) {
        const text = this._recentTranscripts[index] || '';
        if (!text) return;
        const clip = St.Clipboard.get_default();
        clip.set_text(St.ClipboardType.CLIPBOARD, text);
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
