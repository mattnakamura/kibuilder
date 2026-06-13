# Homebrew cask for kibuilder.
#
# This file lives in the *tap* repo, not here — copy it to
# github.com/mattnakamura/homebrew-tap as Casks/kibuilder.rb and fill in
# the sha256 values printed by scripts/make_dmg.sh (or the CI release log).
#
# Users then install with:
#   brew tap mattnakamura/tap
#   brew install --cask kibuilder

cask "kibuilder" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.0"
  sha256 arm:   "fce65dbe83d56486743a641338f2689b018df39ff2a822e9d7f2fe07212b6fe4",
         intel: "945f1142e88ffe4566ffe06d4533d8de28e2e2f77c52962c8976680afdb702b2"

  url "https://github.com/mattnakamura/kibuilder/releases/download/v#{version}/kibuilder-#{version}-#{arch}.dmg"
  name "kibuilder"
  desc "Visual step-by-step assembly guides from KiCAD PCBs"
  homepage "https://github.com/mattnakamura/kibuilder"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on macos: ">= :big_sur"

  app "kibuilder.app"

  caveats <<~EOS
    Board renders require KiCad's command-line tools:
      brew install --cask kicad
  EOS

  zap trash: [
    "~/Library/Preferences/io.github.mattnakamura.kibuilder.plist",
    "~/Library/Saved Application State/io.github.mattnakamura.kibuilder.savedState",
  ]
end
