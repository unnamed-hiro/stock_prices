// StockWidget.swift — ホーム画面ウィジェット: 評価額とリターンを常時表示
//
// 追加手順 (Xcode):
//  1. File → New → Target... → iOS → Widget Extension
//     Product Name: StockWidget / 「Include Configuration App Intent」のチェックを外す
//  2. 生成された StockWidget.swift の中身を、このファイルの内容で全て置き換える
//     (生成された他のファイルはそのままでよい)
//  3. プライベートリポジトリの場合のみ: 両ターゲット (アプリとWidget) の
//     Signing & Capabilities に App Groups を追加し、同じグループ
//     "group.stockaiviewer" を設定 → アプリの設定タブで「接続テスト」を一度実行
//     (設定がウィジェットに共有される)
//  4. ホーム画面長押し → 「+」 → StockWidget を追加

import WidgetKit
import SwiftUI

private let appGroup = "group.stockaiviewer"

struct StockEntry: TimelineEntry {
    let date: Date
    let equity: Double?
    let returnPct: Double?
    let asOf: String
}

struct StockProvider: TimelineProvider {
    func placeholder(in context: Context) -> StockEntry {
        StockEntry(date: .now, equity: 5_263_300, returnPct: 5.27, asOf: "----")
    }

    func getSnapshot(in context: Context, completion: @escaping (StockEntry) -> Void) {
        completion(placeholder(in: context))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<StockEntry>) -> Void) {
        Task {
            let entry = await fetchEntry()
            // 2時間ごとに更新 (データは1日1回しか変わらないため十分)
            let next = Calendar.current.date(byAdding: .hour, value: 2, to: .now)!
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }

    private func fetchEntry() async -> StockEntry {
        // アプリ本体と設定を共有 (App Group)。未設定ならデフォルト値
        let d = UserDefaults(suiteName: appGroup) ?? .standard
        let owner = d.string(forKey: "gh_owner") ?? "unnamed-hiro"
        let repo = d.string(forKey: "gh_repo") ?? "stock_prices"
        let branch = d.string(forKey: "gh_branch") ?? "main"
        let token = d.string(forKey: "github_token") ?? ""

        var comps = URLComponents()
        comps.scheme = "https"
        comps.host = "api.github.com"
        comps.path = "/repos/\(owner)/\(repo)/contents/data/state/portfolio.json"
        comps.queryItems = [URLQueryItem(name: "ref", value: branch)]
        guard let url = comps.url else {
            return StockEntry(date: .now, equity: nil, returnPct: nil, asOf: "URL不正")
        }
        var req = URLRequest(url: url)
        req.setValue("application/vnd.github.raw+json", forHTTPHeaderField: "Accept")
        if !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let curve = obj["equity_curve"] as? [[Any]],
                  let last = curve.last, last.count == 2,
                  let equity = last[1] as? Double,
                  let dateStr = last[0] as? String else {
                return StockEntry(date: .now, equity: nil, returnPct: nil, asOf: "解析不可")
            }
            let initial = (obj["initial_capital"] as? Double) ?? 0
            let deposits = (obj["total_deposits"] as? Double) ?? 0
            let invested = initial + deposits
            let pct = invested > 0 ? (equity - invested) / invested * 100 : 0
            return StockEntry(date: .now, equity: equity, returnPct: pct,
                              asOf: String(dateStr.prefix(10)))
        } catch {
            return StockEntry(date: .now, equity: nil, returnPct: nil, asOf: "通信エラー")
        }
    }
}

struct StockWidgetView: View {
    var entry: StockEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label("AI運用", systemImage: "chart.line.uptrend.xyaxis")
                .font(.caption2.bold())
                .foregroundStyle(.secondary)
            if let eq = entry.equity, let pct = entry.returnPct {
                Text("\(Int(eq).formatted())円")
                    .font(.system(.title3, design: .rounded).bold())
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
                Text(String(format: "%+.2f%%", pct))
                    .font(.headline)
                    .foregroundStyle(pct >= 0 ? .green : .red)
            } else {
                Text("—").font(.title2)
            }
            Spacer(minLength: 0)
            Text(entry.asOf)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .containerBackground(.fill.tertiary, for: .widget)
    }
}

struct StockWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "StockWidget", provider: StockProvider()) { entry in
            StockWidgetView(entry: entry)
        }
        .configurationDisplayName("AI運用口座")
        .description("評価額とリターンをホーム画面に表示")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

@main
struct StockWidgetBundle: WidgetBundle {
    var body: some Widget {
        StockWidget()
    }
}
