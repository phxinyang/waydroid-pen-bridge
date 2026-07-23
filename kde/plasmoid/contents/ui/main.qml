import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root

    property string policy: "auto"
    property string mode: "unavailable"
    property bool proAvailable: false
    property string lastError: ""
    property var commandKinds: ({})
    property bool statusPending: false
    property bool policyPending: false

    Plasmoid.title: "触控笔模式"
    toolTipMainText: "触控笔模式"
    toolTipSubText: modeLabel()

    function modeLabel() {
        const labels = {
            auto: "自动",
            waydroid: "Waydroid",
            desktop: "桌面",
        };
        const modeText = mode === "direct" ? "Waydroid" :
            mode === "desktop" ? "桌面" : "不可用";
        return `${labels[policy] ?? policy} · ${modeText}`;
    }

    function run(arguments_, kind) {
        if (kind === "status" && statusPending)
            return;
        if (kind === "policy" && policyPending)
            return;
        const command = "/usr/local/libexec/waydroid-pen-session " +
            arguments_.join(" ");
        if (kind === "status")
            statusPending = true;
        else if (kind === "policy")
            policyPending = true;
        commandKinds[command] = kind;
        executable.disconnectSource(command);
        executable.connectSource(command);
    }

    function refresh() {
        run(["status"], "status");
    }

    function setPolicy(value) {
        if (!["auto", "waydroid", "desktop"].includes(value))
            return;
        run(["policy", value], "policy");
    }

    function applyStatus(stdout) {
        try {
            const state = JSON.parse(stdout);
            policy = state.policy ?? "auto";
            mode = state.root?.mode ?? state.applied_mode ?? "unavailable";
            proAvailable = state.root?.relay?.pro_available ?? false;
            lastError = state.last_error ?? state.root?.error ?? "";
        } catch (error) {
            lastError = String(error);
        }
    }

    compactRepresentation: Item {
        implicitWidth: Kirigami.Units.gridUnit
        implicitHeight: Kirigami.Units.gridUnit

        Kirigami.Icon {
            anchors.fill: parent
            source: "input-tablet"
            active: compactMouse.containsMouse
        }

        MouseArea {
            id: compactMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.expanded = !root.expanded
        }
    }

    fullRepresentation: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing
        Layout.minimumWidth: Kirigami.Units.gridUnit * 12

        PlasmaComponents3.Label {
            text: "触控笔模式"
            font.bold: true
        }

        Repeater {
            model: [
                {key: "auto", label: "自动"},
                {key: "waydroid", label: "Waydroid"},
                {key: "desktop", label: "桌面"},
            ]

            delegate: PlasmaComponents3.RadioButton {
                required property var modelData
                text: modelData.label
                checked: root.policy === modelData.key
                enabled: !root.policyPending
                onClicked: root.setPolicy(modelData.key)
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
        }

        PlasmaComponents3.Label {
            text: root.modeLabel() + (root.proAvailable ? " · Focus Pen Pro" : "")
            opacity: 0.75
        }

        PlasmaComponents3.Label {
            visible: root.lastError.length > 0
            text: root.lastError
            color: Kirigami.Theme.negativeTextColor
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
    }

    Plasma5Support.DataSource {
        id: executable
        engine: "executable"

        onNewData: function(sourceName, data) {
            disconnectSource(sourceName);
            const kind = root.commandKinds[sourceName] ?? "";
            delete root.commandKinds[sourceName];
            if (kind === "status")
                root.statusPending = false;
            else if (kind === "policy")
                root.policyPending = false;
            const exitCode = Number(data["exit code"] ?? 1);
            if (exitCode !== 0) {
                root.lastError = String(data.stderr ?? "触控笔模式切换失败").trim();
                return;
            }
            if (kind === "status")
                root.applyStatus(String(data.stdout ?? ""));
            else
                root.refresh();
        }
    }

    Timer {
        interval: 2000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }
}
