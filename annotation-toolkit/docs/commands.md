
删除
```
uv run python run.py \
  --delete-dataset medical-case-review-100-20260907 \
  --yes
```

查询
```
uv run python run.py --profile cozie-safety --mode review --dry-run
```

创建
```
uv run python run.py \
  --profile cozie-medical-review \
  --mode review \
  --min-submitted 1 \
  --input workbench/output/cases-2026-09-07T01-19-57-173Z_engine.csv \
  --dataset medical-case-review-100-20260907
```

模板
```
uv run python run.py \
  --profile xxx \
  --mode review \
  --offset xx \
  --limit xx \
  --random \
  --min-submitted xx \
  --guidelines xxx \
  --input xxx \
  --dataset xxx
```

查看数据进度
```
uv run python run.py \
  --progress-dataset medical-safety-review-test
```

导出
```
uv run python run.py \
  --export-dataset medical-safety-review-test
```

创建用户
```
uv run python run.py \
  --create-users 10 \
  --user-prefix prod_reviewer
```

删除用户
```
uv run python run.py \
  --delete-users 10 \
  --user-prefix medical_reviewer
```


```
登录：http://172.17.23.51:6900
账号密码找我私
```
