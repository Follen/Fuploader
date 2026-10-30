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

插件列表官方前端仅一次读取moduleList，尚无其分页参数证据；版本列表已有offset/limit。CLI的version create/update入口和provider实现不能等同schema已注册动作：当前明确注册version.edit/delete，创建可由plugin.update无versionId完成。中央表应以schema实际注册为准。

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

当前未验证：SubscribeLevel非0语义、NeedsPush创建语义、Strategies对象内部完整契约、插件moduleList是否存在未公开分页。2026-10-30动态接口当前返回6个分支；该列表应每次从服务器读取，不能视为永久固定全集。非0等级和NeedsPush创建语义未用远程写入验证。机器表相应condition标明未知，不能从原生UI默认值猜服务端限制。

## 2026-10-30 隔离实测验收

使用已有HTTP会话，仅操作本轮带唯一FuploadProbe标记的对象。初始备份、作者插件与6分支我的分享均为空。`options game-types` 真实返回 wowretail、wowclassicera、wowclassicwlk、wowclassictbc、wowanniversary、wowforever。

在wowretail和wowanniversary各生成一份unknown addon及WTF包，源目录同时有选中和未选角色；ZIP清单确认仅含选中角色，上传后ETag和完整备份读回确认。随后完成rename和私密分享create/update/edit；正文包含富文本与img，ThumbList使用官方静态图片。更新日志与标题后，正文、图片、WTF角色及插件选择均原样保留。两分支只显示各自分享，其余四分支无测试分享。两个备份在存在引用时，delete-preview均拒绝；实际delete入口返回backup_in_use，没有发送remove。

实测修复两处协议适配问题：COS Python SDK需要字符串ContentLength，否则requests在发送前抛InvalidHeader；分享列表摘要不返回BackupID，创建确认必须先取新分享详情再比对绑定。两者均新增可复现回归断言。

上述两份分享和备份已清理。随后对wowclassicera、wowclassicwlk、wowclassictbc、wowforever各用新marker完成最小unknown addon单ZIP生成→上传/完整读回→改名读回→删除预览→删除与负向读回；逐个完成清理后再进入下一分支，始终不积攒云备份。每次均确认返回Strappid匹配、IsClassic=true、WTFList为空。至此当前动态接口返回的全部6分支均完成真实备份生命周期。

经典旧世分支首次删除后列表短暂返回旧记录，首次确认给出verification_required；随后独立只读查询证实已删除，未重发删除请求。已为此补充有限只读轮询及回归测试。最终独立查询确认云备份数0、6分支我的分享均0，本轮共6份备份和2份私密分享全部清理，未修改已有对象。此验收覆盖配置/备份，不代表插件版本发布或非0订阅等级已经实测。
