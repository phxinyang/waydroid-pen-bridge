import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {
    QuickMenuToggle,
    SystemIndicator,
} from 'resource:///org/gnome/shell/ui/quickSettings.js';

const SESSION_HELPER = '/usr/local/libexec/waydroid-pen-session';
const POLICIES = ['auto', 'waydroid', 'desktop'];

function useChineseUi() {
    const candidates = [
        GLib.getenv('LC_ALL'),
        GLib.getenv('LC_MESSAGES'),
        GLib.getenv('LANG'),
    ];
    for (const value of candidates) {
        if (value && value.toLowerCase().startsWith('zh'))
            return true;
    }
    return false;
}

const ZH = useChineseUi();
const LABELS = ZH
    ? {auto: '自动', waydroid: 'Waydroid', desktop: '桌面'}
    : {auto: 'Auto', waydroid: 'Waydroid', desktop: 'Desktop'};
const TITLE = ZH ? '触控笔模式' : 'Pen Mode';

const PenModeToggle = GObject.registerClass(
class PenModeToggle extends QuickMenuToggle {
    constructor(extension) {
        super({
            title: TITLE,
            subtitle: LABELS[extension.policy],
            iconName: 'input-tablet-symbolic',
            menuEnabled: true,
            toggleMode: false,
        });

        this.menu.setHeader('input-tablet-symbolic', TITLE);
        this._items = new Map();
        for (const policy of POLICIES) {
            const item = new PopupMenu.PopupMenuItem(LABELS[policy]);
            item.connect('activate', () => extension.setPolicy(policy));
            this.menu.addMenuItem(item);
            this._items.set(policy, item);
        }
        this.updatePolicy(extension.policy);
    }

    updatePolicy(policy) {
        this.subtitle = LABELS[policy];
        for (const [candidate, item] of this._items)
            item.setOrnament(candidate === policy
                ? PopupMenu.Ornament.CHECK
                : PopupMenu.Ornament.NONE);
    }
});

const PenModeIndicator = GObject.registerClass(
class PenModeIndicator extends SystemIndicator {
    constructor(extension) {
        super();
        this.toggle = new PenModeToggle(extension);
        this.quickSettingsItems.push(this.toggle);
    }

    destroy() {
        this.quickSettingsItems.pop();
        this.toggle.destroy();
        super.destroy();
    }
});

export default class WaydroidPenModeExtension extends Extension {
    enable() {
        this._enabled = true;
        this._policyPath = GLib.build_filenamev([
            GLib.get_user_config_dir(), 'waydroid-pen-mode', 'policy',
        ]);
        this.policy = this._loadPolicy();
        const sourceEpoch = Math.floor(GLib.get_real_time() / 1000);
        const sourceNonce = Math.floor(GLib.get_monotonic_time() % 1000000);
        this._sourceId = `gnome_${sourceEpoch}_${sourceNonce}`;
        this._generation = 0;
        this._overviewActive = Main.overview.visible;
        this._trackedWindow = null;
        this._timerId = 0;
        this._contextRunning = false;
        this._pendingContext = null;

        this._indicator = new PenModeIndicator(this);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
        global.display.connectObject(
            'notify::focus-window', () => {
                this._trackWaydroidWindow();
                this._queueContext();
            }, this);
        Main.overview.connectObject(
            'showing', () => {
                this._overviewActive = true;
                this._queueContext(0);
            },
            'hidden', () => {
                this._overviewActive = false;
                this._queueContext(0);
            },
            this);
        Main.layoutManager.connectObject(
            'monitors-changed', () => this._queueContext(80), this);
        this._trackWaydroidWindow();
        this._queueContext(0);
    }

    disable() {
        this._enabled = false;
        global.display.disconnectObject(this);
        Main.overview.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);
        this._trackedWindow?.disconnectObject(this);
        this._trackedWindow = null;
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
        this._indicator?.destroy();
        this._indicator = null;

        this._generation += 1;
        this._spawnSession([
            'context', this._sourceId, String(this._generation),
            '0', '1', 'none',
        ]);
    }

    setPolicy(policy) {
        if (!POLICIES.includes(policy) || policy === this.policy)
            return;
        this._spawnSession(['policy', policy], succeeded => {
            if (!succeeded || !this._enabled)
                return;
            this.policy = policy;
            this._indicator?.toggle.updatePolicy(policy);
            this._queueContext(0);
        });
    }

    _loadPolicy() {
        try {
            const [ok, bytes] = GLib.file_get_contents(this._policyPath);
            if (ok) {
                const policy = new TextDecoder().decode(bytes).trim();
                if (POLICIES.includes(policy))
                    return policy;
            }
        } catch {
            // The shared session helper creates the default on first use.
        }
        return 'auto';
    }

    _queueContext(delay = 100) {
        if (!this._enabled)
            return;
        if (this._timerId)
            GLib.source_remove(this._timerId);
        this._timerId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, delay, () => {
                this._timerId = 0;
                this._submitContext();
                return GLib.SOURCE_REMOVE;
            });
    }

    _submitContext() {
        this._generation += 1;
        const focused = this._isWaydroidWindow(global.display.focus_window);
        const mapping = this._getWaydroidMapping();
        const arguments_ = [
            'context',
            this._sourceId,
            String(this._generation),
            focused ? '1' : '0',
            this._overviewActive ? '1' : '0',
        ];
        if (mapping)
            arguments_.push(...mapping.map(value => value.toFixed(9)));
        else
            arguments_.push('none');

        if (this._contextRunning) {
            this._pendingContext = arguments_;
            return;
        }
        this._runContext(arguments_);
    }

    _runContext(arguments_) {
        this._contextRunning = true;
        this._spawnSession(arguments_, () => {
            this._contextRunning = false;
            const pending = this._pendingContext;
            this._pendingContext = null;
            if (pending && this._enabled)
                this._runContext(pending);
        });
    }

    _spawnSession(arguments_, done = null) {
        let process;
        try {
            process = Gio.Subprocess.new(
                [SESSION_HELPER, ...arguments_],
                Gio.SubprocessFlags.STDOUT_PIPE |
                Gio.SubprocessFlags.STDERR_PIPE);
        } catch (error) {
            console.error(`Waydroid Pen Mode: ${error.message}`);
            done?.(false);
            return;
        }

        process.communicate_utf8_async(null, null, (source, result) => {
            let succeeded = false;
            try {
                const [, stdout, stderr] = source.communicate_utf8_finish(result);
                succeeded = source.get_successful();
                if (succeeded)
                    console.log(`Waydroid Pen Mode: ${stdout.trim()}`);
                else
                    console.error(`Waydroid Pen Mode: ${stderr.trim()}`);
            } catch (error) {
                console.error(`Waydroid Pen Mode: ${error.message}`);
            }
            done?.(succeeded);
        });
    }

    _isWaydroidWindow(window) {
        if (!window)
            return false;

        const tracker = Shell.WindowTracker.get_default();
        const appId = tracker.get_window_app(window)?.get_id()?.toLowerCase() ?? '';
        const wmClass = window.get_wm_class()?.toLowerCase() ?? '';
        const gtkId = window.get_gtk_application_id()?.toLowerCase() ?? '';
        if (appId.includes('waydroid') || wmClass.includes('waydroid') ||
            gtkId.includes('waydroid'))
            return true;

        const pid = window.get_pid();
        if (pid <= 0)
            return false;
        try {
            const [ok, bytes] = GLib.file_get_contents(`/proc/${pid}/cmdline`);
            if (!ok)
                return false;
            const command = new TextDecoder().decode(bytes).toLowerCase();
            return command.includes('waydroid') ||
                command.includes('android.hardware.graphics.composer');
        } catch {
            return false;
        }
    }

    _findWaydroidWindow() {
        const focused = global.display.focus_window;
        if (this._isWaydroidWindow(focused))
            return focused;
        for (const actor of global.get_window_actors()) {
            const window = actor.metaWindow;
            if (this._isWaydroidWindow(window))
                return window;
        }
        return null;
    }

    _trackWaydroidWindow() {
        const tracked = this._findWaydroidWindow();
        if (tracked === this._trackedWindow)
            return;
        this._trackedWindow?.disconnectObject(this);
        this._trackedWindow = tracked;
        this._trackedWindow?.connectObject(
            'position-changed', () => this._queueContext(80),
            'size-changed', () => this._queueContext(80),
            'notify::fullscreen', () => this._queueContext(80),
            this);
    }

    _getWaydroidMapping() {
        const window = this._findWaydroidWindow();
        if (!window)
            return null;
        const monitorIndex = window.get_monitor();
        const monitor = Main.layoutManager.monitors[monitorIndex];
        if (!monitor)
            return null;

        let rect;
        try {
            rect = window.get_buffer_rect();
        } catch {
            rect = window.get_frame_rect();
        }
        const left = Math.max(rect.x, monitor.x);
        const top = Math.max(rect.y, monitor.y);
        const right = Math.min(rect.x + rect.width, monitor.x + monitor.width);
        const bottom = Math.min(rect.y + rect.height, monitor.y + monitor.height);
        if (right <= left || bottom <= top)
            return null;
        return [
            (left - monitor.x) / monitor.width,
            (top - monitor.y) / monitor.height,
            (right - left) / monitor.width,
            (bottom - top) / monitor.height,
        ];
    }
}
