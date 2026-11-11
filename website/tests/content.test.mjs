import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

const read=path=>readFile(new URL('../'+path,import.meta.url),'utf8');
const config=JSON.parse(await read('site.config.json'));
const installerRepo=new URL(config.repo).pathname.slice(1);
const currentRecord=`docs/development/V${config.version.replaceAll('.','')}-ACCEPTANCE.md`;

test('documented version and verification date are valid',()=>{
  assert.match(config.version,/^\d+\.\d+\.\d+$/);
  assert.match(config.publishedVersion,/^\d+\.\d+\.\d+$/);
  assert.ok(['released','unreleased'].includes(config.releaseStatus));
  const source=config.version.split('.').map(Number);
  const published=config.publishedVersion.split('.').map(Number);
  const difference=source.map((part,index)=>part-published[index]).find(part=>part!==0)||0;
  assert.ok(config.releaseStatus==='released'?difference===0:difference>0);
  assert.match(config.verifiedAt,/^\d{4}-\d{2}-\d{2}$/);
  assert.equal(new Date(config.verifiedAt).toISOString().slice(0,10),config.verifiedAt);
});

test('package and shared product versions match the documented source',async()=>{
  const pkg=JSON.parse(await read('package.json'));
  const lock=JSON.parse(await read('package-lock.json'));
  const source=await readFile(new URL('../../src/tg2cloud/version.py',import.meta.url),'utf8');
  assert.deepEqual([...source.matchAll(/^VERSION\s*=\s*"([^"]+)"\r?$/gm)].map(match=>match[1]),[config.version]);
  assert.equal(pkg.version,config.version);
  assert.equal(lock.version,config.version);
  assert.equal(lock.packages[''].version,config.version);
});

test('downloads point to published assets and source checkout respects release status',async()=>{
  const download=await read('docs/download.md');
  const links=[...download.matchAll(/\]\((https:\/\/[^\s)]+\/releases\/download\/[^\s)]+)\)/g)].map(match=>match[1]);
  const expected=[`TG2Cloud-v${config.publishedVersion}-source.tar.gz`,'SHA256SUMS.txt']
    .map(name=>`${config.repo}/releases/download/v${config.publishedVersion}/${name}`);
  assert.deepEqual(links.sort(),expected.sort());
  assert.ok(download.includes(`${config.repo}/releases/tag/v${config.publishedVersion}`));
  assert.ok(download.includes(`**TG2Cloud v${config.version}**`));
  if(config.releaseStatus==='unreleased'){
    assert.ok(download.includes('待发布'));
    assert.ok(!download.includes(`${config.repo}/releases/tag/v${config.version}`));
    assert.ok(!download.includes(`${config.repo}/releases/download/v${config.version}/`));
  }
  assert.doesNotMatch(download,/releases\/download\/[^)\s]+\.exe|build\.ps1 -Edition/);
  const development=await read('docs/reference/development.md');
  const checkout=config.releaseStatus==='released'?`v${config.version}`:'main';
  assert.deepEqual([...development.matchAll(/^git checkout (\S+)\r?$/gm)].map(match=>match[1]),[checkout]);
  assert.ok(development.includes('git switch main'));
  assert.doesNotMatch(development,/requirements-build\.txt|build\.ps1|恢复.*部署器构建/);
});

test('developer source links follow the public script-only layout',async()=>{
  const template=await read('src/templates.mjs');
  const guide=await read('docs/reference/development.md');
  for(const path of ['src/tg2cloud/deployment/profiles.py','.github/CONTRIBUTING.md','.github/SECURITY.md']){
    assert.ok(template.includes(`'${path}'`));
    assert.ok(await readFile(new URL('../../'+path,import.meta.url),'utf8'));
  }
  assert.ok(guide.includes('src/tg2cloud/deployment/resources.py'));
  assert.ok(!guide.includes('legacy/desktop/'));
});

test('latest changelog entry matches source version without claiming an unpublished release',async()=>{
  const changelog=await read('docs/changelog.md');
  const latest=changelog.match(/^## TG2Cloud v(\d+\.\d+\.\d+)\r?$/m);
  assert.equal(latest?.[1],config.version);
  assert.ok(changelog.includes(`${config.repo}/releases/tag/v${config.publishedVersion}`));
  if(config.releaseStatus==='unreleased'){
    const current=changelog.split(/^## /m)[1];
    assert.ok(current.includes('待发布'));
    assert.ok(current.includes(`${config.repo}/blob/main/CHANGELOG.md`));
    assert.ok(!changelog.includes(`${config.repo}/releases/tag/v${config.version}`));
  }
});

test('management menu matches source labels and keeps old-version boundaries',async()=>{
  const source=await readFile(new URL('../../src/tg2cloud/cli/management.py',import.meta.url),'utf8');
  const items=source.match(/MENU_ITEMS = \(([\s\S]*?)\r?\n\)/)?.[1];
  assert.ok(items);
  const entries=[...items.matchAll(/\((\d+), "([^"]+)"\)/g)].map(match=>[match[1],match[2]]);
  assert.deepEqual(entries.map(([number])=>number),[...Array.from({length:16},(_,index)=>String(index+1)),'0']);
  assert.deepEqual(entries.slice(0,14).map(([,label])=>label),[
    '安装与升级','查看运行状态','查看运行日志','服务启停管理','Bot 用户管理','WebDAV 凭据','HTTPS 与管理',
    '文件分类设置','异常通知设置','业务就绪检查','WebDAV 验收','故障诊断报告','数据备份管理','卸载当前实例']);
  assert.deepEqual(entries[14],['15','外部 WebDAV']);
  assert.deepEqual(entries[15],['16','监听管理']);
  const article=await read('docs/operations/maintenance.md');
  const guide=await readFile(new URL('../../docs/OPERATIONS.md',import.meta.url),'utf8');
  for(const [number,label] of entries){
    assert.ok(article.includes(`${(number+'.').padEnd(3)} ${label}`),label);
    assert.ok(guide.includes(`| ${number} | ${label} |`),label);
  }
  for(const text of ['v1.4.4 菜单','旧版 v1.4.3','更新文档不会更新 VPS','tg2cloud naming-preview']){
    assert.ok(article.includes(text),text);
  }
  assert.ok(!entries.some(([,label])=>label.includes('命名预览')));
  for(const text of ['v1.4.7','历史正式 v1.4.6 尚无此选项','无需额外安装命令','当前 Edition','不重启 Bot／网关']){
    assert.ok(article.includes(text),text);
  }
});

test('external WebDAV unified entry retains optional lifecycle and published-version boundaries',async()=>{
  const article=await read('docs/deploy/external-webdav.md');
  const guide=await readFile(new URL('../../docs/external-webdav.md',import.meta.url),'utf8');
  for(const text of ['v1.4.7','15. 外部 WebDAV','历史正式 v1.4.6 尚无','10. 用户管理','返回主菜单','不重启 Bot']){
    assert.ok(article.includes(text),text);
    assert.ok(guide.includes(text),text);
  }
  assert.ok(article.includes('## 独立安装'),'preserve the website legacy section anchor');
  assert.ok(guide.includes('## 独立入口'),'preserve the repository guide legacy section anchor');
  for(const content of [article,guide]){
    assert.ok(!content.includes('bash <(curl -fsSL https://raw.githubusercontent.com/LuoPoJunZi/TG2Cloud/main/install-webdav.sh)'),
      'the unified menu does not require a separate installation command');
    assert.ok(content.includes('install-webdav.sh')&&content.includes('历史')&&content.includes('Tag'));
    assert.ok(content.includes('API 2'),'describe the explicit new layout and legacy migration');
    assert.ok(content.includes('/status'));
  }
});

test('installation feedback distinguishes evidence from manual acceptance',async()=>{
  const update=await read('docs/operations/update.md');
  for(const text of ['v1.4.4','旧 v1.4.3 工具不包含新增反馈','[信息]','[提醒]','[待核对]','[错误]','20 秒',
                    'WebDAV 写入与大小复验：未执行','实际 Telegram 转存：待人工验收',
                    '公网访问：待外部网络验收','原命令退出码','用户中断时不追加读取']){
    assert.ok(update.includes(text),text);
  }
  const guide=await readFile(new URL('../../docs/OPERATIONS.md',import.meta.url),'utf8');
  for(const text of ['v1.4.4','显式参数模式的 `TG2CLOUD_*` 标记保持原样',
                    '不持久化原日志','不新增生产数据库字段','不因就绪未确认自动重启或回退']){
    assert.ok(guide.includes(text),text);
  }
  const faq=await read('docs/faq.md');
  assert.ok(faq.includes('旧工具须显式升级后使用'));
});

test('content source metadata matches the site configuration',async()=>{
  for(const path of ['README.md','THIRD_PARTY_NOTICES.md']){
    const content=await read(path);
    assert.ok(content.includes(`TG2Cloud v${config.version}`),path);
    assert.ok(content.includes(config.verifiedAt),path);
  }
  const sources=await read('docs/reference/sources.md');
  assert.ok(sources.includes(`**v${config.version}**`));
  assert.ok(sources.includes(`${config.repo}/releases/tag/v${config.publishedVersion}`));
  if(config.releaseStatus==='unreleased'){
    assert.ok(sources.includes('待发布'));
    assert.ok(!sources.includes(`${config.repo}/releases/tag/v${config.version}`));
  }
  const [year,month,day]=config.verifiedAt.split('-').map(Number);
  assert.ok(sources.includes(`**${year} 年 ${month} 月 ${day} 日**`));
});

test('VPS one-line entry is consistent with the root user guide',async()=>{
  const command=`bash <(curl -fsSL https://raw.githubusercontent.com/${installerRepo}/main/install.sh)`;
  const download=await read('docs/download.md');
  const guide=await readFile(new URL('../../docs/VPS-INSTALL.md',import.meta.url),'utf8');
  const readme=await readFile(new URL('../../README.md',import.meta.url),'utf8');
  const english=await readFile(new URL('../../README_EN.md',import.meta.url),'utf8');
  for(const content of [download,guide,readme,english])assert.ok(content.includes(command));
  assert.ok(download.includes('只读预检'));
  assert.ok(download.includes('真实 VPS'));
  assert.ok(download.includes(currentRecord));
});

test('LAN installation and unified uninstall agree with root guides',async()=>{
  const download=await read('docs/download.md');
  const readme=await readFile(new URL('../../README.md',import.meta.url),'utf8');
  const english=await readFile(new URL('../../README_EN.md',import.meta.url),'utf8');
  for(const [script,guide] of [['install-lan.sh','LAN-INSTALL.md']]){
    const command=`bash <(curl -fsSL https://raw.githubusercontent.com/${installerRepo}/main/${script})`;
    const source=await readFile(new URL(`../../docs/${guide}`,import.meta.url),'utf8');
    for(const content of [download,readme,english,source])assert.ok(content.includes(command),script);
  }
  assert.ok(download.includes('卸载不是升级步骤'));
  assert.ok(download.includes('默认完整卸载'));
  assert.ok(download.includes('确认后清理所选实例数据'));
  assert.ok(download.includes('--keep-data'));
  assert.ok(download.includes('不等于把 VPS 恢复到安装前'));
  const guide=await readFile(new URL('../../docs/UNINSTALL.md',import.meta.url),'utf8');
  const command='tg2cloud uninstall --edition all --check';
  for(const content of [download,readme,english,guide])assert.ok(content.includes(command));
  for(const content of [download,readme,english,guide]){
    assert.ok(!content.includes('https://raw.githubusercontent.com/LuoPoJunZi/TG2Cloud/main/uninstall.sh'));
    assert.ok(!content.includes('https://raw.githubusercontent.com/LuoPoJunZi/TG2Cloud/main/install-webdav.sh'));
  }
  assert.ok(download.includes('15. 外部 WebDAV'));
});

test('website brand copies match the canonical repository assets byte for byte',async()=>{
  const pairs=[
    ['tg2cloud.ico','favicon.ico'],
    ...['tg2cloud-icon.svg','tg2cloud-icon-32.png','tg2cloud-icon-64.png','tg2cloud-icon-256.png']
      .map(name=>[name,`assets/${name}`])
  ];
  const digest=buffer=>createHash('sha256').update(buffer).digest('hex');
  for(const [canonical,copy] of pairs){
    const original=await readFile(new URL(`../../assets/brand/${canonical}`,import.meta.url));
    const website=await readFile(new URL(`../public/${copy}`,import.meta.url));
    assert.equal(digest(website),digest(original),`${copy} must be copied unchanged from assets/brand/${canonical}`);
  }
});

test('historical acceptance stays traceable through immutable links rather than current tutorials',async()=>{
  const history=await readFile(new URL('../../CHANGELOG.md',import.meta.url),'utf8');
  for(const version of ['130','143','144','145']){
    assert.match(history,new RegExp(`/blob/[0-9a-f]{40}/docs/development/V${version}-ACCEPTANCE\\.md`));
  }
  const index=await readFile(new URL('../../docs/README.md',import.meta.url),'utf8');
  assert.ok(index.includes('(../CHANGELOG.md)'));
  assert.ok(index.includes(`(development/V${config.version.replaceAll('.','')}-ACCEPTANCE.md)`));
  assert.doesNotMatch(index,/\]\(development\/V(?:130|143|144|145)-ACCEPTANCE\.md\)/);
});

test('current release evidence separates actual CI and assets from unrun real services',async()=>{
  const record=await readFile(new URL('../../'+currentRecord,import.meta.url),'utf8');
  for(const value of ['同标签原生双架构','真实用户 VPS','尚未执行','SHA256','schema 3',
    `TG2Cloud-v${config.version}-source.tar.gz`,`TG2Cloud-v${config.version}-compose-clouddrive2.tar.gz`,
    `TG2Cloud-v${config.version}-compose-openlist.tar.gz` ])assert.ok(record.includes(value),value);
  if(config.releaseStatus==='released'){
    assert.match(record,/actions\/runs\/\d+/);
    assert.ok(record.includes(`${config.repo}/releases/tag/v${config.version}`));
    assert.match(record,new RegExp(`ghcr[.]io/${installerRepo.toLowerCase()}@sha256:[0-9a-f]{64}`));
  }else{
    assert.ok(record.includes('待发布'));
    assert.ok(record.includes('当前未生成'));
    assert.doesNotMatch(record,/状态：[^\n]*(?:已正式发布|已发布完成)/);
  }
  assert.doesNotMatch(record,/root@|\b(?:\d{1,3}\.){3}\d{1,3}\b|config-[A-Za-z0-9]{8,}\.tar\.gz/);
});

test('current configuration retains existing databases and private Sessions without offering cross-project migration',async()=>{
  const configGuide=await readFile(new URL('../../docs/CONFIGURATION.md',import.meta.url),'utf8');
  const backup=await readFile(new URL('../../docs/BACKUP-RESTORE.md',import.meta.url),'utf8');
  for(const text of ['tg2cloud.db','tg115.db','Session','备份']){
    assert.ok(configGuide.includes(text),text);
    assert.ok(backup.includes(text),text);
  }
  assert.ok(backup.includes('不等于服务已恢复'));
  assert.ok(backup.includes('不能只降级镜像'));
  const article=await read('docs/reference/config.md');
  assert.ok(article.includes('tg115.db'));
  assert.ok(!config.navigation.flatMap(group=>group.items).some(item=>item.slug==='operations/migration'));
});

test('current upgrade guide requires independent business acceptance and keeps safe failure behavior',async()=>{
  const guide=await read('docs/operations/update.md');
  for(const text of ['原命令退出码','用户中断时不追加读取','20 秒','WebDAV 写入与大小复验：未执行',
    '实际 Telegram 转存：待人工验收','公网访问：待外部网络验收','不提供强制覆盖选项',
    'Compose','不能通过改版本号或删数据绕过'])assert.ok(guide.includes(text),text);
  assert.doesNotMatch(guide,/releases\/download\/[^)\s]+\.exe|build\.ps1|\/operations\/migration\//);
});

test('current helper identity in installation docs matches every public entry',async()=>{
  const guide=await readFile(new URL('../../docs/VPS-INSTALL.md',import.meta.url),'utf8');
  const removal=await readFile(new URL('../../docs/UNINSTALL.md',import.meta.url),'utf8');
  const english=await readFile(new URL('../../README_EN.md',import.meta.url),'utf8');
  const chinese=await readFile(new URL('../../README.md',import.meta.url),'utf8');
  const development=await read('docs/reference/development.md');
  const pins=[];
  for(const name of ['install.sh','install-lan.sh']){
    const entry=await readFile(new URL('../../'+name,import.meta.url),'utf8');
    const matches=[...entry.matchAll(/^installer_commit\s*=\s*"([0-9a-f]{40})"\r?$/gm)];
    assert.equal(matches.length,1,name);
    pins.push(matches[0][1]);
  }
  assert.equal(new Set(pins).size,1);
  // Exact helper identities belong in the full guides. Landing pages must link
  // to both guides instead of copying internal commit details into the overview.
  for(const [name,content] of [['VPS guide',guide],['uninstall',removal],['website development',development]]){
    assert.ok(content.includes('`'+pins[0]+'`'),name);
  }
  for(const [name,content] of [['English README',english],['Chinese README',chinese]]){
    for(const guide of ['VPS-INSTALL.md','UNINSTALL.md']){
      assert.ok(content.includes('](docs/'+guide+')'),name+': '+guide);
    }
  }
  const recovery=await readFile(new URL('../../docs/RECOVERY.md',import.meta.url),'utf8');
  assert.ok(!guide.includes('新布局尚未发布'));
  assert.ok(!development.includes('新布局只完成本地候选准备'));
  assert.ok(!recovery.includes('尚未进入 v1.3.0 Release'));
});

test('root READMEs use current topic navigation and a dedicated current documentation index',async()=>{
  const index=await readFile(new URL('../../docs/README.md',import.meta.url),'utf8');
  for(const name of ['VPS-INSTALL','LAN-INSTALL','COMPOSE','BOT-USAGE','STORAGE','LISTENING','BACKUP-RESTORE','UNINSTALL']){
    assert.ok(index.includes(`](${name}.md)`),name);
  }
  for(const [name,heading] of [['README.md','## 使用文档'],['README_EN.md','## Documentation']]){
    const content=await readFile(new URL('../../'+name,import.meta.url),'utf8');
    const start=content.indexOf(heading);assert.ok(start>=0,name);
    const section=content.slice(start+heading.length).split(/\r?\n## /)[0];
    for(const target of ['docs/README.md','RELEASE_NOTES.md','docs/FEATURE-ENHANCEMENTS.md',
      'docs/DOCKER-NGINX.md','docs/COMPOSE.md','docs/development/DEVELOPMENT.md',currentRecord]){
      assert.ok(section.includes('('+target+')'),name+': '+target);
    }
    const paragraphs=section.split(/\r?\n\s*\r?\n/).map(block=>block.trim()).filter(block=>block&&!block.startsWith('|'));
    assert.equal(paragraphs.length,1,name+': short introduction then topic navigation');
    assert.doesNotMatch(section,/MIGRATION_FROM_TG115|README-小白|SCRIPT-FIRST|V144-ACCEPTANCE/);
  }
});

test('retired desktop and migration guides are absent from the public documentation surface',async()=>{
  for(const path of ['docs/README-小白使用说明.md','docs/MIGRATION_FROM_TG115.md','website/docs/operations/migration.md']){
    await assert.rejects(readFile(new URL('../../'+path,import.meta.url)),{code:'ENOENT'});
  }
  const downloads=await read('docs/download.md');
  assert.doesNotMatch(downloads,/Deployer\.exe|Get-FileHash|build\.ps1/);
  const credits=await read('docs/reference/credits.md');
  assert.ok(credits.includes('whyhhh20/TG115'));
  assert.ok(credits.includes('MIT'));
  assert.ok(await readFile(new URL('../../LICENSE',import.meta.url)));
});

test('root READMEs keep repository-first documentation and aligned author cards',async()=>{
  const base='https://tg2cloud.pages.dev/';
  for(const name of ['README.md','README_EN.md']){
    const content=await readFile(new URL('../../'+name,import.meta.url),'utf8');
    assert.ok(content.includes(base),name+': documentation home');
    assert.ok(content.includes('href="docs/README.md"'),name+': repository index');
    assert.ok(content.includes('assets/brand/tg2cloud-logo.svg'),name+': canonical brand');
    assert.ok(content.includes('https://github.com/whyhhh20/TG115'),name+': upstream credit');
    for(const target of ['LICENSE','.github/CONTRIBUTING.md','.github/SECURITY.md',
      'docs/VPS-INSTALL.md','docs/LAN-INSTALL.md','docs/填写信息清单.md','docs/OPERATIONS.md',
      'docs/RECOVERY.md','docs/UNINSTALL.md','docs/COMPOSE.md',
      'docs/development/REPOSITORY.md','docs/development/DEVELOPMENT.md','CHANGELOG.md','RELEASE_NOTES.md']){
      assert.ok(content.includes('('+target+')'),name+': direct repository link '+target);
    }
    const attribution=name==='README.md'?'## 致谢与项目来源':'## Acknowledgements and Project Origin';
    const license=name==='README.md'?'## 许可证与免责声明':'## License and Disclaimer';
    const credits=content.slice(content.indexOf(attribution),content.indexOf(license));
    assert.ok(content.includes(attribution),name+': attribution heading');
    assert.ok(content.includes(license),name+': separate license section');
    assert.match(credits,/<table>[\s\S]*<\/table>/,name+': author table');
    const cards=[...credits.matchAll(/<td\b([^>]*)>([\s\S]*?)<\/td>/g)];
    assert.ok(cards.length>=2,name+': retain both authors and allow additional contributors');
    for(const [,attributes,body] of cards){
      for(const attribute of ['align="center"','width="260"','valign="top"']){
        assert.ok(attributes.includes(attribute),name+': consistent author card '+attribute);
      }
      assert.match(attributes,/\bnowrap(?:\s|$)/,name+': names and roles stay on one line');
      assert.match(body,/<img\b[^>]*\bwidth="72"[^>]*\bheight="72"/,name+': equal square avatars');
      const role=body.match(/<sub>([\s\S]*?)<\/sub>/);
      assert.ok(role,name+': author role');
      assert.doesNotMatch(role[1],/<br\b/i,name+': no forced role line breaks');
    }
    const roles=name==='README.md'
      ?['TG2Cloud 项目维护者','上游 TG115 项目原作者']
      :['TG2Cloud maintainer','Original author of upstream TG115'];
    for(const role of roles)assert.ok(credits.includes('<sub>'+role+'</sub>'),name+': '+role);
    for(const author of ['LuoPoJunZi','whyhhh20']){
      assert.ok(credits.includes(`src="https://github.com/${author}.png?size=96" width="72" height="72"`),name+': original author avatar');
    }
    const links=[...content.matchAll(/\]\(([^)]+)\)|\b(?:href|src)="([^"]+)"/g)]
      .map(match=>match[1]||match[2]);
    for(const href of links){
      assert.ok(!href.startsWith('website/'),name+': do not link website source files as user guides');
      if(href.startsWith(base)){
        assert.equal(href,base,name+': article navigation must open repository documents');
      }else if(!/^(?:https?:|#)/.test(href)){
        assert.ok(await readFile(new URL('../../'+href,import.meta.url)),name+': missing local link '+href);
      }
    }
    const removal=content.match(/^tg2cloud uninstall .*$/gm)||[];
    assert.ok(removal.length>0,name+': removal preview');
    assert.ok(removal.every(command=>command.includes('--check')),name+': no immediate removal in the landing page');
    assert.ok(content.includes('--keep-data'),name+': data-preservation option');
  }
});
