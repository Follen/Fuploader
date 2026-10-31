# 小黑盒字段与协议审计

审计日期：2026-10-30。逐字段机器表见同目录 `blackbox.json`，每项含 wire、stage、condition、evidence；覆盖当前 `SCHEMAS` 注册的全部黑盒写入字段，并补充只读命令与 configuration 内部字段。类型、必填项由中央 schema 总表提供，此表记录字段如何进入协议。

## 来源与可复核位置

| 范围 | 一手代码 | 定位 |
| --- | --- | --- |
| 插件元数据、版本 | 已保存的官方 Open 前端 `static.max-c.com__index-B2qQ5GFk.js`；未给出产品版本号，不能标作2.10.19原生代码 | 第1行，PluginInfoForm.getFormData offset3749；ge/update offset868；PluginVersionList.M/upsert offset8824；B/delete offset9037 |
| 分享编辑与条件 | 安装版 Desktop2.10.19，`heybox.wow-workshop`1.1.3，SDK声明^1.2.0，`view/assets/index-C7aTznJw.js` | 第1行，ke offset13189；Yl offset12270；Xe/Ze offset4706 |
| 备份分配、凭据、完成保存 | 同版本扩展 `extension.mjs` | 第250行，createBackup offset2285946；credential offset2279110；finishUpload offset2286071 |
| 动态游戏分支 | 同版本扩展 `extension.mjs` | 第101行，JA中的GET调用 offset689680：`/wow/v2/dynamic_conf/`，target `heybox-workshop`，解析result.strappidInfos |
| WTF manifest | 同版本扩展 `extension.mjs` | 第88行 offset615560，RealmCharacters由WtfSubInfo映射Player/Realm |
| 原生签名 | app.asar `client-update-channel.store-DWqW8hAd.js` | 第4行 offset1883005，jrn/Wrn/Zrn，交错字符串截20再MD5 |
| 原生身份恢复 | app.asar `main-runtime-CQ5zr8us.js` | 第3021行 offset2794880，v8e；R/ce(VX)恢复，Ie/De检查cookie一致 |
| 当前官网登录 | 官方当前 `login-index.js`（ignored analyze/blackbox-phone-login） | 第1行 jn offset272138、JH offset534692、p$ offset549464；精确wire已实测的研究脚本与生产HTTP/auth模块一致 |

安装版资源根：`C:/Program Files (x86)/Qingfeng/Qingfeng/HeyboxDesktop/versions/2.10.19/resources`。所有 offset 为UTF-8解码后字符串索引。压缩文件一行很长，函数名及offset比整行摘录更容易复核。仓库实现证据为 `fupload/scripts/fupload_cli/blackbox.py`、`blackbox_config.py`、`blackbox_backup.py`、`blackbox_http.py`、`blackbox_auth.py` 的对应方法。

## 插件与版本

插件详情编辑先读当前 module，再合并9个发布字段。JSON snake_case 映射为平台 `logoUrl/categoryIds/officialUrl/coreFolders` 等 form 字段；`core_folders` 数组转逗号字符串。`desc` 保持完整文本；未提供的已有字段保留。UI在插件类型9时显示核心目录。

`plugin update` 是版本 upsert 的CLI别名，不是插件元数据编辑。版本字段为 `moduleId, versionId(更新时), name, type, gameVersions(逗号连接), fileUrl`，空业务query。`file` 是本地ZIP输入，经上传取得fileUrl后写版本；不是远程JSON字段。编辑不给新file/file_url时使用现版本fileUrlHeybox。删除只有一次POST，后续只读检查auditState/消失；请求失败或结果不稳定不自动重放。

插件列表当前官方协议一次读取完整moduleList，表格明确pagination:false；版本列表另有offset/limit分页。2026-10-31实测默认请求和三组分页参数均返回同一组3个插件，无分页元数据，顺序可变。CLI的version create/update入口和provider实现不能等同schema已注册动作：当前明确注册version.edit/delete，创建可由plugin.update无versionId完成。中央表应以schema实际注册为准。

## 配置分享

创建与更新的form只有 `configuration=JSON.stringify(完整对象)`，业务query是backup_id，更新再加share_id。删除复用update，query额外delete=1，没有configuration正文。

完整对象从经ID验证的备份开始构造。ID/IsClassic/Strappid不接受用户覆写；更换backup_id要求显式重选KnownAddons、UnknownAddons、WTFList、Materials、Fonts，避免继承旧角色。更新保留未改Article、UpdateLog、ThumbList及完整容器元数据；不是把稀疏patch直接送API。文件选择容器只能提交Files，容器Host/Path等沿用备份。

已落实官方本地提交条件：

- 至少选择一项插件、角色、材质或字体内容。
- Open=true至少一张ThumbList预览图。
- Title非空，且严格还原JS `replace(/[^\x00-\xff]/g,"ab").length<=70`。Latin-1字符权重1，BMP中码点>255字符权重2，astral字符因UTF-16 surrogate pair权重4。

官方编辑器当前把SubscribeLevel赋0；这只是已观察默认值，非0的业务语义未核实，不能推断服务端禁止非0。NeedsPush在官方代码中只为更新通知订阅者而设置；创建时效果未核实。ChatInviteCode官方来自选择房间的invite_code，CLI目前接受string但未再查询房间归属。

KnownAddons按ID、文件按Name、WTF按账号及Realm/Player检查属于绑定备份。当前没有逐字段强制比较调用者提供的KnownAddons或Files对象与原对象的每个元数据值，中央表不要把这个选择校验描述为“全部元数据不可改”。

## 备份

本地scan返回候选目录和明确账号/角色，不联网上传，也不通过目录名自动识别平台KnownAddons。generate/create要求显式四类选择数组；空数组表示不选。已知插件需真实平台brief `ID,Name,Strategy,VersionID`，而非自行猜ID。

unknown_addons从Interface/AddOns打包，materials从Interface打包，fonts仅Fonts内.ttf。wtf_accounts采用 `{name,characters:[{realm,player}]}`，映射Name/RealmCharacters/Characters。每账号ZIP包括选中角色与该账号共享rootfiles/SavedVariables，不包括其它角色目录。manifest记录每个archive字节数、MD5和SHA256；上传前校验路径、内容清单、角色与哈希绑定。

上传真实链路为：create_backup分配ID与MaxSize → 每archive按backup_id/file_type取临时COS凭据 → COS PUT且SDK retry=0、检查ETag=MD5 → save_user_configuration（query.backup_id，form.configuration=base64 UTF-8 JSON） → 从完整backupList按ID读回验证。file_type已证实unknownModules/wtf/materials/fonts。generate本地路径、output_dir、manifest_file不是直接API参数。

备份get没有单独接口，使用list完整对象按ID精确匹配。rename为query backup_id/new_name。批量删除是逐项remove请求，不是批量HTTP接口：先验证全部ID和目标游戏的全部现有分享，空页才视为分享列表完成；关联未知、重复分页、超页数均阻止删除；每项发送前重查引用，发送后有限次数轮询只读列表，默认最多10次、间隔2秒；已有verify_attempts/verify_interval可控制等待。列表接口本身是POST，轮询不重发remove或其它mutation。期间存在的服务端并发创建分享没有原子条件删除接口证据，不能声称跨客户端事务锁。

## 登录与续期

正式默认是纯HTTP与本机CurrentUser DPAPI，不启动浏览器、不隐式发短信。每个业务会话实例首次请求前GET restore_login一次，必须与已选账号UID一致，使用服务器expire_at及返回pkey更新。续期失败返回login_required，POST不重放。

SMS手机号使用固定官方1024位RSA PKCS1v15，加密+86与号码拼接结果。发验证码body为phone_num，登录query为code且body仍phone_num。本机config只允许借用acc_config.xhh_token_id的有效B设备凭据到内存，不借用客户端账户cookie认证，不接受调用者token/路径。它不是恢复会话的必需条件。

真正微信链是web_sso→官方微信OAuth页面/二维码→长轮询→服务端callback→wechat/state。get_qrcode_url/qr_state属于小黑盒App扫码，两者不能混用。OAuth参数与图片从本次官方响应提取并验证固定host/path。

active与pending分开加密，使用Windows用户绑定DPAPI。pending不覆盖active，确认登录成功后才切换。已有SMS主会话默认优先；旧微信单独文件需要显式选择。旧cookie期限不当作服务器期限，在restore得到expire_at前不保存v2迁移。设备B凭据不持久化到active/pending。

官网会在成功restore后重设本地7天cookie；风控SDK重新取deviceId后重设本地14天cookie。这不证明服务器无限滚动续期。未发现仅凭旧B的刷新API或refresh_token协议。

## 旧文档需删除或改写的条目

- “默认启动persistent Chromium、headless probe、过期后打开登录页”的描述已与正式默认不符。原blackbox_web兼容实现存在不等于正常登录路径会启动它。
- “完全不读desktop config”应收窄为“不借用desktop账户cookie认证”；SMS可读取固定本机官方设备风险字段。
- “1.14.1原生API工坊relogin，所以配置/备份不可复用”的旧结论不能外推到2.10.19或新网页会话；Open插件权限、配置分享权限、备份权限必须分别验证。
- 不将改本地cookie expiry写成服务端必然续期；不将SDK获取B/D转换写成旧B可独立续期。
- 不将scan目录候选写成已完成服务端插件识别；不将配置发布JSON和备份保存base64 JSON混为同一编码。

## 已明确的未知项

当前未验证：SubscribeLevel非0语义、NeedsPush创建语义、Strategies对象内部完整契约。2026-10-30动态接口当前返回6个分支；该列表应每次从服务器读取，不能视为永久固定全集。非0等级和NeedsPush创建语义未用远程写入验证。机器表相应condition标明未知，不能从原生UI默认值猜服务端限制。

## 2026-10-30 隔离实测验收

使用已有HTTP会话，仅操作本轮带唯一FuploadProbe标记的对象。初始备份、作者插件与6分支我的分享均为空。`options game-types` 真实返回 wowretail、wowclassicera、wowclassicwlk、wowclassictbc、wowanniversary、wowforever。

在wowretail和wowanniversary各生成一份unknown addon及WTF包，源目录同时有选中和未选角色；ZIP清单确认仅含选中角色，上传后ETag和完整备份读回确认。随后完成rename和私密分享create/update/edit；正文包含富文本与img，ThumbList使用官方静态图片。更新日志与标题后，正文、图片、WTF角色及插件选择均原样保留。两分支只显示各自分享，其余四分支无测试分享。两个备份在存在引用时，delete-preview均拒绝；实际delete入口返回backup_in_use，没有发送remove。

实测修复两处协议适配问题：COS Python SDK需要字符串ContentLength，否则requests在发送前抛InvalidHeader；分享列表摘要不返回BackupID，创建确认必须先取新分享详情再比对绑定。两者均新增可复现回归断言。

上述两份分享和备份已清理。随后对wowclassicera、wowclassicwlk、wowclassictbc、wowforever各用新marker完成最小unknown addon单ZIP生成→上传/完整读回→改名读回→删除预览→删除与负向读回；逐个完成清理后再进入下一分支，始终不积攒云备份。每次均确认返回Strappid匹配、IsClassic=true、WTFList为空。至此当前动态接口返回的全部6分支均完成真实备份生命周期。

经典旧世分支首次删除后列表短暂返回旧记录，首次确认给出verification_required；随后独立只读查询证实已删除，未重发删除请求。已为此补充有限只读轮询及回归测试。最终独立查询确认云备份数0、6分支我的分享均0，本轮共6份备份和2份私密分享全部清理，未修改已有对象。此验收覆盖配置/备份，不代表插件版本发布或非0订阅等级已经实测。


## WA原生接口与CLI补齐

Desktop2.10.19的`WaEditor.vue_vue_type_style_index_1_lang-BCttcQdD.js`已给出create/update配置字段，`index-D2mjhRUP.js`给出owned分页、详情版本和delete:1。CLI新增wa create/update/edit/delete/list/get/categories，精确字段映射在机器表wa项中。

只读实测确认：分类result.list为145组、TagList.Key为string；详情直接返回Slug、HeyboxId、Encoded、Name、Description、UpdateLog、ThumbList、Categories、AuditState、CanView，缺少open/strappid/subscribeLevel。故每次更新都要求这三个不可读业务值显式输入，其余字段保留原详情。作者身份由当前session恢复与get_user_info双重核对。Encoded全部只输出长度/摘要；错误回显不保留原响应或异常链。

官方编辑器固定open=true。2026-10-31首次合成写入open:false后，独立无cookie会话仍满足可访问判定，写入返回visibility_mismatch；该对象1920159771已清理并负读回。正式schema/provider要求外层scope=public；scope=private或缺省在任何请求前拒绝。原始open可为false，但不能宣传私密WA。后续实测证明详情与字符串是独立入口：匿名detail可能failed或Encoded为空，匿名get_wa_string仍返回完整合成串；已删除生产中的旧私密判定helper，不能只凭详情拒绝声明私密。成功结果以verified_fields/unverified_fields区分可读回字段：subscribeLevel、screens.thumb、open本身不宣称已持久化核验。六动态分支真机结果见下节。

当前官网新chunk `index-DiSpld6I.js`提供ORIGINAL/MODIFIED插件submit及CurseForge认领，新提交包含首个ZIP版本并进入审核，页面说明结果通过站内信通知。仍未找到模块容器delete或审核撤回入口；现有delete仅针对module_version。此结论是已读官方入口的范围，不等同服务端绝无内部管理接口。


## 2026-10-31 WA六分支真实验收

本轮先验证当前恢复会话和作者身份，六分支owned WA基线均0；只创建带唯一FuploadWA标记、禁用加载的合成WA。最终完整轮次为 `FuploadWA-20261031-021304-38cac0`，使用scope=public、原始open=false、subscribeLevel=0；每支完成清理后才进入下一支。

| strappid | 本轮临时slug | 结果 |
| --- | --- | --- |
| wowretail | 1920185871 | create/get/update/edit/delete与负读回通过 |
| wowclassicera | 1920192011 | create/get/update/edit/delete与负读回通过 |
| wowclassicwlk | 1920208164 | create/get/update/edit/delete与负读回通过 |
| wowclassictbc | 1920216315 | create/get/update/edit/delete与负读回通过 |
| wowanniversary | 1920223066 | create/get/update/edit/delete与负读回通过 |
| wowforever | 1920232426 | create/get/update/edit/delete与负读回通过 |

更新使用新的合成原串和更新日志；稀疏编辑仅改标题，其余HTML正文、img、主图、分类与原串保持精确一致。创建和编辑后都用独立无cookie HTTP客户端查询：detail返回CanView=true但Encoded为空，get_wa_string返回非空Encoded，摘要精确匹配本轮合成串。这直接证明open=false不能作为私密权限。原串仅在内存对比，日志只记录长度/摘要与布尔判据，不保存或输出内容。

公开路径open=true另用临时1920165358验证：写入成功后AuditState=1，官方UI禁用删除；在已验证owner后对同一对象直发一次已证delete:1，业务status=failed且对象仍在，未重放该请求。随后本轮清理授权下，完整保留内容、仅将open改false，状态立即1→2，之后新的一次delete返回ok且负读回成功。未记录首次失败的完整业务msg，因此不把该响应具体拒因写成已证审核规则。审核中该对象的匿名detail返回failed，但匿名get_wa_string仍能取回完整合成串。

首个open=false范围探测1920159771和一次匿名只读网络异常中止的1920178708也均已清理；未重复任何不明写请求。全轮6项及此前3项测试对象共9项均清理。最终owned列表六分支均0，逐slug的provider与独立CLI get均not_found，基线保持。受控证据在本机ignored analyze/blackbox-live-acceptance对应FuploadWA目录的journal.json/events.jsonl、pending-cleanup.json和cli-smoke.json；正式协议证据为上述2.10.19官方模块与生产blackbox_wa.py/schema.py方法。

插件模块后续已获用户明确授权单次提交并创建本轮测试模块，最新验收与保留范围见下节；仍无已证模块容器删除或撤审入口。

## 配置 unlisted 的真实访问语义

本轮单 retail 临时配置 owner 详情为 Open=false；匿名仅 share_id 仍可取相同正文和 Code，安装接口无 Code 拒绝、有该 Code 返回一条下载签名；匿名 backup_id 直接下载拒绝。未下载原始 WTF，探针只存长度、SHA、布尔和状态，分享码及签名 URL 不落盘。该开关是隐藏列表，不能承诺访问隔离；临时分享与备份均已单次删除并负读回，证据 `analyze/blackbox-live-acceptance/FuploadPrivateConfig-20261031-023936-e6729304/privacy.json`。


## 2026-10-31 插件提交与版本地址转换

用户明确授权后，仅用合成惰性插件提交一次官方plugin.submit：ORIGINAL、Alpha=3、开发工具1031、gameVersionIds="12.1.7"、初版0.0.1。当前选项接口和官网N/J调用表明gameVersionIds实际是版本文本CSV，不是数值ID。正式生产未新增plugin.create；一次临时研究提交的实际result键为createdAt/moduleId/status，当前官网代码仍取module_id，不能以该前端取值拼写代替实际响应。

当前账号owned列表及detail核对出模块211855824，初版211855825（0.0.1、type3、auditState2）。plugin.edit已通过并将说明恢复。初次额外0.0.2（211855929）upsert业务ok，但服务端把官方上传intake URL转换成正式fileUrlHeybox，原来的严格字符串比较给出verification_required；该额外版本已单次删除并稳定读回auditState4，初版未改。

现已落实的最小兼容仅用于新本地file上传创建：上传源须为严格官方HTTPS /wow/module/...zip；必须找到唯一新正整数version ID，name/type/gameVersions精确读回，且版本列表当前result.strappidInfos把所选版本唯一映射到同一分支。只有严格官方HTTPS /wow/wow_module_file/<同分支>/<32位小写hex>.zip能作为server_canonicalization元数据读回。缺映射、分支不符/歧义、外域、端口/query、坏路径、重复匹配或旧ID均继续verification_required。调用者file_url不走该例外；既有无新file的编辑有下述单独的原record来源校验。

版本upsert的verified=true含义明确限定为verification_scope=remote_metadata，metadata_verified=true与verified_fields说明哪些元数据已核对；archive_verification.content_verified=false、public_download_verified=false，unverified_fields包含archive_bytes。它不证明包字节相同、匿名可下载或审核完成。匿名读取本轮上传和canonical ZIP均遇HTTP403，未将目录中的32位名称推断为本机ZIP的MD5。

修复后用新惰性0.0.3（211856992）通过正式schema+execute_write完成plugin.update：预期intake地址、实际canonical地址和name/type/games在清理前保存，返回上述metadata-only成功。随后无新file的version.edit请求也业务ok且name读回变更，但平台再次改写canonical hash；当时严格已有URL规则返回verification_required，没有重发编辑。该额外版本已单次删除并经10秒稳定读回auditState4，初版与模块保留，无额外活动版本。因此补充单独的metadata-edit例外：必须无file且无caller file_url，输入URL仅从本次同moduleId/versionId的唯一原record获取；原记录ID、模块绑定及其URL来源可追溯，前后均严格同一动态分支的官方canonical路径，同一已知version ID与目标name/type/games精确读回，才接受server_recanonicalization。caller file_url、未知/重复来源、错ID/module、外域或分支变化仍拒绝；不泛化为任意地址变化成功。

受控本机证据为ignored analyze/blackbox-plugin-submit-plan-20261031/FuploadTemp10313C7F/{submission.json,managed-lifecycle.json,canonical-readback.json,canonical-lifecycle.json}；协议来源为当前官网index-DiSpld6I.js的J/N与index-CfH3ZfOW.js的PluginVersionList.v（编辑时将fileUrlHeybox作为fileUrl输入）。模块及初版属于本次授权保留资源，尚无可保证移除容器的官方入口。


最终用新的0.0.4（211857744）经正式schema+execute_write完整通过plugin.update、version.edit、version.delete：初次上传intake→canonical使用server_canonicalization；编辑只改版本名称、无file/file_url，从同一已知原record的canonical→同branch新canonical使用server_recanonicalization，输出同时包含source=existing_version_record、source_module_id/source_version_id/source_archive_url。所有元数据、原URL来源及实际地址都在删除前记录。两次upsert的metadata_verified=true、verification_scope=remote_metadata，archive content/public download标志均false。删除仅一次，随后10秒稳定读回auditState4。之前0.0.2和0.0.3也均为4；无额外活动版本，模块211855824与原版211855825保留。连此前plugin.edit，四个现有插件写入口均已真实通过；完整新证据为同目录canonical-lifecycle-0.0.4.json。

此兼容不扩展到既有version.edit显式提交新file或caller file_url后的任意地址变化：若不能按原有URL精确读回，仍需verification_required并先只读核验。它也不把初版或额外版本的auditState数字等同于已确认可公开下载。

### 2026-10-31 正式 CLI 微信登录补测

通过正式 `session login-start` 生成微信二维码，用户扫码确认后，`session login-status` 返回 `authenticated:true`、`api_ready:true`、`method:wechat`。随后按顺序执行 `session doctor`、`backup list`、`plugin list` 均成功，验证了二维码到业务接口的完整链路。全程仅 HTTP 与 CLI，没有操作浏览器或客户端界面。原二维码过期路径与短信登录此前已测；本次成功回调后才替换 active 会话。证据保存在 ignored `analyze/full-live-20261031/blackbox-wechat-status-new.json` 与 `blackbox-wechat-business-new.json`。


## 2026-10-31 补验官方签名下载与不公开分享的实际内容

保留的授权临时模块211855824、初版211855825已补验实际下载。安装版2.10.19官方 `heybox.wow-workshop/extension.mjs` 的 `getInstallModuleInfo`（offset2282643）先GET `/wow/get_download_sign/`，参数为 `strappid`、`versionId`、`encrypt=1`，按同文件 `Rq` 的AES-128-CBC格式解密结果，再由 `downloadOneModule` 使用 `LatestVersion.FileUrlHeybox?sign=...`。本轮严格使用该正常下载链路，未在日志保存签名或登录凭据。

下载HTTP200、1083字节，MD5与官方 `FileMd5Heybox` 一致。原始本地ZIP为967字节，服务端重新打包后的容器字节不同；排除目录项后文件名全集相同，TOC、惰性Lua和README三个文件逐字节相同。初版记录读前读后未改变，审核状态仍为2。此前不带签名的直链403只说明该URL需要签名，不能据此认定正常下载链路失败。证据：`analyze/blackbox-plugin-submit-plan-20261031/FuploadTemp10313C7F/signed-download-readback.json`。这是保留版本的独立实测；当前provider每次upsert仍只自动核对远程元数据，不能把本轮结论泛化为每次上传均已自动验包或已通过审核。

另建全新纯合成 `Open:false` 分享1920315317及备份6296235补验WTF实际ZIP。匿名只凭share_id的detail返回同一Code；不带Code的install请求失败，带该Code可取得签名。官方 `downloadBackup`（offset623945）使用 `https://WtfAccount.Host/WtfAccount.Path?sign=...`，当前Host为 `wowbackup.max-c.com`，不是先前测试脚本误设的COS域名。本轮按官方地址匿名GET成功，HTTP200、539字节，MD5与该备份对象一致；两个文件均为本轮合成账号的测试内容，按Windows CRLF规范比较一致。未访问任何用户真实WTF。分享与备份随后均删除，远程列表恢复原有0/0基线。证据：`analyze/blackbox-live-acceptance/FuploadPrivateConfigVerify-20261031-105148-0b5241da/privacy.json`。因此 `Open:false` 的“不出现在公开列表”语义已验证到实际内容下载，不应作为私有隔离边界。

本轮未对付费或通知契约发送试探写入。官方模块列表页面仍只调用一次无分页参数的列表方法，版本列表明确带offset/limit；单模块账号不能证明服务端不存在未公开分页。官方备份源码能定位Strategies使用的 `ID`、`Strategy`、可选 `LockVersion`，策略枚举0/1/2/5以及锁版本取Id/Name；它不能证明完整服务端扩展契约。SubscribeLevel非0的付费含义、NeedsPush创建后的通知含义、Strategies未观察扩展字段、以及WA详情未回显的open/subscribeLevel/thumb，继续保留为未证实项，不写成通过。

### 插件列表分页补核

2026-10-31 对照官方 `index-CfH3ZfOW.js`：页面调用 `pe()` 不传分页参数，取 `result.moduleList`，PluginList 表格使用 `pagination:!1`。同一包的 PluginVersionList 则明确传 `offset/limit` 并读取 `total`，两者不是同一种列表协议。实际已登录账号默认查询返回3项；`offset=0/limit=1`、`offset=1/limit=1`、`page=2/pageSize=1` 均返回相同3个ID，响应仅含moduleList，顺序可变。Fupload 保持一次获取插件列表，不循环请求无效分页参数；版本列表保留现有分页处理。此项从待验证清单移除；未制造额外公开模块来测试假定的隐藏上限。只读证据：ignored `analyze/blackbox-pagination-20261031/probe.json`。

### 审计修复：版本短页与已有版本换包

版本列表现在按实际页长度推进offset，有总数时必须恰好读全；总数变化、提前空页、无效或重复ID均返回待核验。无总数时只以空页结束，不能将短页当成完整列表。删除后的负读回使用同一完整性检查，避免漏掉后页中的目标。

正式version.edit附带本地ZIP时，上传前核对唯一原版本、module和官方分支，保留原canonical URL。写后要求同一版本身份、精确目标元数据、同一官方分支，且地址已从原包变化；只允许本次本地上传的官方intake到canonical路径。旧地址未变、外部地址或身份不一致均待核验，不重放上传或写入。返回server_replacement_canonicalization，验证范围仍为remote_metadata，archive_bytes仍未自动验证。本轮修复为离线回归，没有新增远程写入。
