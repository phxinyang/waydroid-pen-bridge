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
    // Debounced focus that is actually reported to the session helper.
    property bool reportedFocused: false
    property bool pendingFocused: false
    property var pendingMapping: null

    readonly property int enterFocusMs: 80
    readonly property int leaveFocusMs: 450
    readonly property int geometryMs: 150

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

    function quantizeMapping(mapping) {
        if (!mapping)
            return "none";
        return mapping.map(value => String(Math.round(value * 1000000000))).join(".");
    }

    function contextSignature(focused, mapping) {
        const parts = [
            focused ? "1" : "0",
            overviewActive ? "1" : "0",
            quantizeMapping(mapping),
        ];
        return parts.join(".");
    }

    function contextToken(signature) {
        generation += 1;
        return `ctx.${sourceId}.${generation}.${signature}`;
    }

    function liveFocused() {
        return isWaydroidWindow(Workspace.activeWindow);
    }

    function evaluateFocus() {
        const focused = liveFocused();
        if (focused === pendingFocused)
            return;
        pendingFocused = focused;
        // Enter Waydroid quickly; leave slowly so brief focus blips do not
        // thrash desktop/direct routing while writing.
        focusTimer.interval = focused ? enterFocusMs : leaveFocusMs;
        focusTimer.restart();
    }

    function evaluateGeometry() {
        pendingMapping = mappingForWindow(findWaydroidWindow());
        geometryTimer.restart();
    }

    function publish(focused, mapping) {
        const signature = contextSignature(focused, mapping);
        if (signature === lastSignature)
            return;
        lastSignature = signature;
        reportedFocused = focused;
        const unit = `waydroid-pen-session@${contextToken(signature)}.service`;
        startUnit.arguments = [unit, "replace"];
        startUnit.call();
    }

    function reportNow() {
        publish(reportedFocused, mappingForWindow(findWaydroidWindow()));
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
        // Overview must force desktop immediately.
        focusTimer.stop();
        pendingFocused = false;
        reportedFocused = false;
        publish(false, mappingForWindow(findWaydroidWindow()));
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
        id: focusTimer
        interval: 80
        repeat: false
        onTriggered: {
            const mapping = mappingForWindow(findWaydroidWindow());
            root.publish(root.pendingFocused, mapping);
        }
    }

    Timer {
        id: geometryTimer
        interval: 150
        repeat: false
        onTriggered: {
            // Geometry updates keep the debounced focus value so a resize
            // never races a pending leave-focus timer.
            root.publish(root.reportedFocused, root.pendingMapping);
        }
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
            root.evaluateFocus();
            root.evaluateGeometry();
        }

        function onWindowAdded() {
            root.updateTrackedWindow();
            root.evaluateFocus();
            root.evaluateGeometry();
        }

        function onWindowRemoved() {
            root.updateTrackedWindow();
            root.evaluateFocus();
            root.evaluateGeometry();
        }

        function onScreensChanged() {
            root.evaluateGeometry();
        }
    }

    Connections {
        target: root.trackedWindow
        ignoreUnknownSignals: true

        function onBufferGeometryChanged() {
            root.evaluateGeometry();
        }

        function onFrameGeometryChanged() {
            root.evaluateGeometry();
        }

        function onFullScreenChanged() {
            root.evaluateGeometry();
        }

        function onOutputChanged() {
            root.evaluateGeometry();
        }
    }

    Component.onCompleted: {
        updateTrackedWindow();
        pendingFocused = liveFocused();
        reportedFocused = pendingFocused;
        publish(reportedFocused, mappingForWindow(findWaydroidWindow()));
    }

    Component.onDestruction: {
        generation += 1;
        const unit = `waydroid-pen-session@ctx.${sourceId}.${generation}.0.1.none.service`;
        startUnit.arguments = [unit, "replace"];
        startUnit.call();
    }
}
