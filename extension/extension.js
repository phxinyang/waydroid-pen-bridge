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

const HELPER = '/usr/local/libexec/waydroid-pen-mode';
const POLICIES = ['auto', 'waydroid', 'desktop'];
const LABELS = {
    auto: '自动',
    waydroid: 'Waydroid',
    desktop: '桌面',
};

const PenModeToggle = GObject.registerClass(
class PenModeToggle extends QuickMenuToggle {
    constructor(extension) {
        super({
            title: '触控笔模式',
            subtitle: LABELS[extension.policy],
            iconName: 'input-tablet-symbolic',
            menuEnabled: true,
            toggleMode: false,
        });

        this.menu.setHeader('input-tablet-symbolic', '触控笔模式');
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
        this._desiredMode = null;
        this._appliedMode = null;
        this._running = false;
        this._timerId = 0;

        this._indicator = new PenModeIndicator(this);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
        global.display.connectObject(
            'notify::focus-window', () => {
                if (this.policy === 'auto')
                    this._queueSync();
            }, this);
        this._queueSync();
    }

    disable() {
        this._enabled = false;
        global.display.disconnectObject(this);
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
        this._indicator?.destroy();
        this._indicator = null;

        this._desiredMode = 'desktop';
        this._runDesiredMode();
    }

    setPolicy(policy) {
        if (!POLICIES.includes(policy) || policy === this.policy)
            return;
        this.policy = policy;
        GLib.mkdir_with_parents(GLib.path_get_dirname(this._policyPath), 0o700);
        GLib.file_set_contents(this._policyPath, policy);
        this._indicator?.toggle.updatePolicy(policy);
        this._queueSync();
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
            // The default is safe and needs no persisted file.
        }
        return 'auto';
    }

    _queueSync(delay = null) {
        let mode;
        if (this.policy === 'waydroid')
            mode = 'direct';
        else if (this.policy === 'desktop')
            mode = 'desktop';
        else
            mode = this._isWaydroidFocused() ? 'direct' : 'desktop';
        this._desiredMode = mode;

        if (this._timerId)
            GLib.source_remove(this._timerId);
        const timeout = delay ?? (mode === 'direct' ? 50 : 150);
        this._timerId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, timeout, () => {
                this._timerId = 0;
                this._runDesiredMode();
                return GLib.SOURCE_REMOVE;
            });
    }

    _isWaydroidFocused() {
        const window = global.display.focus_window;
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

    _runDesiredMode() {
        if (this._running || !this._desiredMode ||
            this._desiredMode === this._appliedMode)
            return;

        const requestedMode = this._desiredMode;
        this._running = true;
        let process;
        try {
            process = Gio.Subprocess.new(
                ['sudo', '-n', HELPER, requestedMode],
                Gio.SubprocessFlags.STDOUT_PIPE |
                Gio.SubprocessFlags.STDERR_PIPE);
        } catch (error) {
            console.error(`Waydroid Pen Mode: ${error.message}`);
            this._running = false;
            this._queueSync(2000);
            return;
        }

        process.communicate_utf8_async(null, null, (source, result) => {
            let succeeded = false;
            try {
                const [, stdout, stderr] = source.communicate_utf8_finish(result);
                if (source.get_successful()) {
                    succeeded = true;
                    this._appliedMode = requestedMode;
                    console.log(`Waydroid Pen Mode: ${stdout.trim()}`);
                } else {
                    console.error(`Waydroid Pen Mode: ${stderr.trim()}`);
                }
            } catch (error) {
                console.error(`Waydroid Pen Mode: ${error.message}`);
            } finally {
                this._running = false;
                if (this._enabled && this._desiredMode !== this._appliedMode)
                    this._queueSync(succeeded ? 0 : 2000);
            }
        });
    }
}
