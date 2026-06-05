# data/

## analytics.csv
Google Analytics 4からエクスポートしたPV/CVデータ。
毎月末に手動またはGA4 APIで更新。

フォーマット:
```
url,title,date,pv,cv
```

## affiliate-YYYY-MM.csv
A8.net等のASPからエクスポートした月次データ。
毎月1日に前月分をエクスポートして配置。

フォーマット:
```
program_name,generated_amount,confirmed_amount,approval_rate,clicks
GKSキャリア,35000,35000,1.0,120
ツインプロ,75200,75200,1.0,45
```
