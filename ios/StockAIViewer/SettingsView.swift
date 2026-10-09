// SettingsView.swift — リポジトリ接続設定

import SwiftUI

struct SettingsView: View {
    @AppStorage("gh_owner") private var owner = "unnamed-hiro"
    @AppStorage("gh_repo") private var repo = "stock_prices"
    @AppStorage("gh_branch") private var branch = "main"
    @AppStorage("github_token") private var token = ""
    @State private var testResult: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("GitHub リポジトリ") {
                    TextField("オーナー", text: $owner)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("リポジトリ名", text: $repo)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("ブランチ", text: $branch)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    SecureField("Fine-grained PAT (read-only)", text: $token)
                } header: {
                    Text("アクセストークン")
                } footer: {
                    Text("""
                    プライベートリポジトリの場合のみ必要です。GitHub → Settings → \
                    Developer settings → Fine-grained personal access tokens で、\
                    対象をこのリポジトリに限定し、権限は Contents: Read-only だけを \
                    付与したトークンを作成してください。読み取り専用なので、万一漏れても \
                    売買や変更はできません。
                    """)
                }

                Section {
                    Button("接続テスト") { Task { await test() } }
                    if let r = testResult {
                        Text(r).font(.callout)
                    }
                }

                Section("このアプリについて") {
                    Text("""
                    このアプリは閲覧専用です。売買判断は GitHub Actions 上の \
                    システムが毎営業日 16:00 (JST) に実行し、このアプリはその結果を \
                    表示するだけです。アプリから発注・変更は一切できません。
                    """)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("設定")
        }
    }

    private func test() async {
        mirrorToAppGroup()
        do {
            _ = try await GitHubClient().file("data/state/portfolio.json",
                                              as: PortfolioState.self)
            testResult = "✅ 接続成功 — 口座データを取得できました"
        } catch {
            testResult = "❌ \(error.localizedDescription)"
        }
    }

    /// ウィジェット (別プロセス) と設定を共有する。App Groups 未設定なら何もしない
    private func mirrorToAppGroup() {
        guard let g = UserDefaults(suiteName: "group.stockaiviewer") else { return }
        g.set(owner, forKey: "gh_owner")
        g.set(repo, forKey: "gh_repo")
        g.set(branch, forKey: "gh_branch")
        g.set(token, forKey: "github_token")
    }
}
