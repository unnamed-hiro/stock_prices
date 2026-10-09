// DailyReportsView.swift — 日次レポートの一覧と詳細 (AI判断・約定・見送り)

import SwiftUI

struct DailyReportsView: View {
    @State private var files: [RepoFile] = []
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Group {
                if files.isEmpty, let e = error {
                    ContentUnavailableView("取得エラー", systemImage: "wifi.exclamationmark",
                                           description: Text(e))
                } else if files.isEmpty {
                    ProgressView("読み込み中...")
                } else {
                    List(files) { f in
                        NavigationLink(String(f.name.dropLast(5))) {
                            DailyDetailView(path: f.path, title: String(f.name.dropLast(5)))
                        }
                    }
                }
            }
            .navigationTitle("日次レポート")
            .refreshable { await load() }
            .task { if files.isEmpty { await load() } }
        }
    }

    private func load() async {
        do {
            let all = try await GitHubClient().list("results/daily")
            files = all.filter { $0.name.hasSuffix(".json") }
                       .sorted { $0.name > $1.name }   // 新しい日付が先頭
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

struct DailyDetailView: View {
    let path: String
    let title: String
    @State private var report: DailyReport?
    @State private var error: String?

    var body: some View {
        Group {
            if let r = report {
                detail(r)
            } else if let e = error {
                ContentUnavailableView("取得エラー", systemImage: "wifi.exclamationmark",
                                       description: Text(e))
            } else {
                ProgressView()
            }
        }
        .navigationTitle(title)
        .task { await load() }
    }

    @ViewBuilder
    private func detail(_ r: DailyReport) -> some View {
        List {
            Section("サマリー") {
                LabeledContent("戦略", value: r.strategy)
                LabeledContent("評価額", value: yen(r.endingEquity))
                let pnl = r.endingEquity - r.startingEquity
                LabeledContent("前日比") {
                    Text(yen(pnl))
                        .foregroundStyle(pnl >= 0 ? .green : .red)
                }
                LabeledContent("保有銘柄数", value: "\(r.nPositions)")
                if let regime = r.regime {
                    LabeledContent("市場レジーム") {
                        Text(regime == "risk_off" ? "⚠️ リスクオフ (新規買い停止)" : "リスクオン")
                            .foregroundStyle(regime == "risk_off" ? .orange : .green)
                    }
                }
            }

            if !r.executedBuys.isEmpty {
                Section("約定: 買い (\(r.executedBuys.count))") {
                    ForEach(r.executedBuys) { o in
                        row(main: "\(o["ticker"])  \(o["shares"])株 @\(o["price"])円",
                            sub: o["reason"])
                    }
                }
            }
            if !r.exits.isEmpty || !r.executedSells.isEmpty {
                Section("約定: 決済 (\(r.exits.count + r.executedSells.count))") {
                    ForEach(r.exits) { o in
                        row(main: "\(o["ticker"])  \(o["return_pct"])%", sub: o["reason"])
                    }
                    ForEach(r.executedSells) { o in
                        row(main: "\(o["ticker"])  \(o["return_pct"])%", sub: o["reason"])
                    }
                }
            }
            if !r.plannedOrders.isEmpty {
                Section("翌営業日の始値で約定予定 (\(r.plannedOrders.count))") {
                    ForEach(r.plannedOrders) { o in
                        row(main: "[\(o["side"] == "buy" ? "買" : "売")] \(o["ticker"])",
                            sub: o["reason"])
                    }
                }
            }
            if !r.skipped.isEmpty {
                Section("見送り (\(r.skipped.count))") {
                    ForEach(r.skipped) { o in
                        row(main: o["ticker"], sub: o["reason"])
                    }
                }
            }
        }
    }

    private func row(main: String, sub: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(main)
            if !sub.isEmpty {
                Text(sub).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func load() async {
        do {
            report = try await GitHubClient().file(path, as: DailyReport.self)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
