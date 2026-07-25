import QtQuick
import org.kde.kwin

Item {
    id: root

    property int generation: 0
    property string sourceId: "kde_" + String(Date.now()) + "_" +
        String(Math.floor(Math.random() * 1000000))
    property bool overviewActive: false
    property var trackedWindow: null
    property string lastSignature: ""

    function isWaydroidWindow(window) {
        if (!window)
            return false;
        const identity = [
            window.resourceName ?? "",
            window.resourceClass ?? "",
            window.caption ?? "",
        ].join(" ").toLowerCase();
        return identity.includes("waydroid") ||
            identity.includes("android.hardware.graphics.composer");
    }

    function findWaydroidWindow() {
        if (isWaydroidWindow(Workspace.activeWindow))
            return Workspace.activeWindow;
        for (const window of Workspace.windows) {
            if (isWaydroidWindow(window))
                return window;
        }
        return null;
    }

    function updateTrackedWindow() {
        trackedWindow = findWaydroidWindow();
    }

    function mappingForWindow(window) {
        if (!window || !window.output)
            return null;
        const rect = window.bufferGeometry ?? window.frameGeometry;
        const output = window.output.geometry;
        if (!rect || !output || output.width <= 0 || output.height <= 0)
            return null;
        const left = Math.max(rect.x, output.x);
        const top = Math.max(rect.y, output.y);
        const right = Math.min(rect.x + rect.width, output.x + output.width);
        const bottom = Math.min(rect.y + rect.height, output.y + output.height);
        if (right <= left || bottom <= top)
            return null;
        return [
            (left - output.x) / output.width,
            (top - output.y) / output.height,
            (right - left) / output.width,
            (bottom - top) / output.height,
        ];
    }

    function contextSignature() {
        const focused = isWaydroidWindow(Workspace.activeWindow) ? 1 : 0;
        const mapping = mappingForWindow(findWaydroidWindow());
        const parts = [
            String(focused),
            overviewActive ? "1" : "0",
        ];
        if (mapping) {
            for (const value of mapping)
                parts.push(String(Math.round(value * 1000000000)));
        } else {
            parts.push("none");
        }
        return parts.join(".");
    }

    function contextToken(signature) {
        generation += 1;
        return `ctx.${sourceId}.${generation}.${signature}`;
    }

    function scheduleReport(delay) {
        reportTimer.interval = delay ?? 80;
        reportTimer.restart();
    }

    function reportContext() {
        // Only start a session unit when focus/overview/geometry actually
        // changed.  Bumping generation on every timer tick flooded systemd
        // with identical desktop applies and delayed real mode switches.
        const signature = contextSignature();
        if (signature === lastSignature)
            return;
        lastSignature = signature;
        const unit = `waydroid-pen-session@${contextToken(signature)}.service`;
        startUnit.arguments = [unit, "replace"];
        startUnit.call();
    }

    function updateOverview(returnValue) {
        let text = String(returnValue).toLowerCase();
        try {
            text += " " + JSON.stringify(returnValue).toLowerCase();
        } catch (error) {
            // The string representation is enough for a D-Bus string list.
        }
        const active = text.includes("overview") || text.includes("windowview");
        if (active === overviewActive)
            return;
        overviewActive = active;
        scheduleReport(0);
    }

    DBusCall {
        id: startUnit
        service: "org.freedesktop.systemd1"
        path: "/org/freedesktop/systemd1"
        dbusInterface: "org.freedesktop.systemd1.Manager"
        method: "StartUnit"
        onFailed: error => console.warn(`Waydroid Pen Mode: ${error}`)
    }

    DBusCall {
        id: activeEffects
        service: "org.kde.KWin"
        path: "/Effects"
        dbusInterface: "org.freedesktop.DBus.Properties"
        method: "Get"
        arguments: ["org.kde.kwin.Effects", "activeEffects"]
        onFinished: returnValue => root.updateOverview(returnValue)
    }

    Timer {
        id: reportTimer
        interval: 80
        repeat: false
        onTriggered: root.reportContext()
    }

    Timer {
        interval: 250
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: activeEffects.call()
    }

    Connections {
        target: Workspace

        function onWindowActivated() {
            root.updateTrackedWindow();
            root.scheduleReport(50);
        }

        function onWindowAdded() {
            root.updateTrackedWindow();
            root.scheduleReport(80);
        }

        function onWindowRemoved() {
            root.updateTrackedWindow();
            root.scheduleReport(0);
        }

        function onScreensChanged() {
            root.scheduleReport(80);
        }
    }

    Connections {
        target: root.trackedWindow
        ignoreUnknownSignals: true

        function onBufferGeometryChanged() {
            root.scheduleReport(80);
        }

        function onFrameGeometryChanged() {
            root.scheduleReport(80);
        }

        function onFullScreenChanged() {
            root.scheduleReport(80);
        }

        function onOutputChanged() {
            root.scheduleReport(80);
        }
    }

    Component.onCompleted: {
        updateTrackedWindow();
        scheduleReport(0);
    }

    Component.onDestruction: {
        generation += 1;
        const unit = `waydroid-pen-session@ctx.${sourceId}.${generation}.0.1.none.service`;
        startUnit.arguments = [unit, "replace"];
        startUnit.call();
    }
}
