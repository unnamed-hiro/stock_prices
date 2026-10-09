// StockAIViewerApp.swift
// AI株取引シミュレーターの運用状況を確認する iOS アプリ
//
// 設計: このアプリは「ビューア」であり、売買判断は一切行わない。
// 毎営業日の判断は GitHub Actions が実行し、結果 (JSON) をリポジトリに
// コミットする。アプリはその JSON を GitHub API 経由で取得して表示する。

import SwiftUI

@main
struct StockAIViewerApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    @AppStorage("github_token") private var token = ""

    var body: some View {
        TabView {
            DashboardView()
                .tabItem { Label("口座", systemImage: "chart.line.uptrend.xyaxis") }
            DailyReportsView()
                .tabItem { Label("日次", systemImage: "calendar.day.timeline.left") }
            MonthlyReportsView()
                .tabItem { Label("月次", systemImage: "doc.text.magnifyingglass") }
            SettingsView()
                .tabItem { Label("設定", systemImage: "gearshape") }
        }
    }
}
