<!--
Short guide for using two GitHub accounts (company and personal) on one machine.
Covers SSH keys, SSH config aliases, setting remotes per-repo, and verification.
Use this to switch this project between `sinmeraji` and `smerajiapply` accounts.
-->

## Git multi-account setup (SSH)

Aliases configured on this machine:
- Personal account `sinmeraji`: alias `github-personal-sin`, key `~/.ssh/id_ed25519_github_personal2`
- Company account `smerajiapply`: alias `github-company`, key `~/.ssh/id_ed25519_github_company`

### 1) Generate keys (only once)
```bash
ssh-keygen -t ed25519 -C "sinmeraji@github-personal2" -f ~/.ssh/id_ed25519_github_personal2 -N ""
ssh-keygen -t ed25519 -C "smerajiapply@github-company" -f ~/.ssh/id_ed25519_github_company -N ""
```

### 2) SSH config (`~/.ssh/config`)
```sshconfig
Host github-personal-sin
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_github_personal2
  IdentitiesOnly yes

Host github-company
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_github_company
  IdentitiesOnly yes
```

Add each public key to the correct GitHub account (Settings → SSH and GPG keys).

### 3) Verify which account an alias uses
```bash
ssh -T github-personal-sin   # expect: Hi sinmeraji!
ssh -T github-company        # expect: Hi smerajiapply!
```

### 4) Point a repo at the desired account
- Set this project to personal (`sinmeraji/SPLLM`):
```bash
git remote set-url origin git@github-personal-sin:sinmeraji/SPLLM.git
```
- Example for a company repo:
```bash
git remote set-url origin git@github-company:<org-or-user>/<repo>.git
```

### 5) Push
```bash
git push -u origin main
```

Tips
- If GitHub authenticates as the wrong user, ensure the right alias is used in `origin` and that the public key is added to the intended GitHub account.
- To force a specific key temporarily:
```bash
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_github_personal2 -o IdentitiesOnly=yes" git push
```


